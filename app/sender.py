from app.db import tx

class SendResult:
    def __init__(self, status: str, reason: str = ""):
        self.status = status
        self.reason = reason

    @property
    def is_success(self) -> bool:
        return self.status == "sent"

    def __repr__(self):
        return f"SendResult({self.status}, {self.reason!r})"

def _sent_today(db) -> int:
    row = db.execute("""
        SELECT COUNT(*) FROM messages
        WHERE status='sent' AND date(sent_at) = date('now')
    """).fetchone()
    return row[0]

def recover_stuck_messages(db, timeout_seconds: int = 300) -> int:
    """
    Scans for messages stuck in 'sending' state for longer than timeout_seconds (default 5 min).
    Marks them as 'failed' with explicit note requiring human review before retry.
    
    CRITICAL RELIABILITY INVARIANT:
    We do NOT auto-reset to 'approved' or auto-retry because the external API may have
    actually delivered the DM to the recipient right before the crash. Auto-retrying
    without manual verification would risk violating the non-negotiable 'never double-message' rule.
    """
    with tx(db):
        cur = db.execute("""
            UPDATE messages
            SET status='failed',
                status_detail='App crashed or timed out during dispatch. Manual verification required on X before retrying.'
            WHERE status='sending'
              AND (strftime('%s', 'now') - strftime('%s', COALESCE(sent_at, approved_at, 'now'))) > ?
        """, (timeout_seconds,))
        return cur.rowcount

def send_message(db, x_client, cfg, msg_id: int) -> SendResult:
    """
    Pure Python dispatch engine. Enforces state transitions:
    approved -> sending -> sent | blocked | failed

    Zero UI dependencies: purely returns a SendResult object.
    """
    # Layer 1: Atomically claim via atomic UPDATE. Only one concurrent process can win this.
    with tx(db):
        cur = db.execute(
            "UPDATE messages SET status='sending' "
            "WHERE id=? AND status='approved'",
            (msg_id,),
        )
        claimed = cur.rowcount == 1

    if not claimed:
        return SendResult("blocked", "not_approved_or_already_claimed")

    msg = db.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    lead = db.execute("SELECT * FROM leads WHERE user_id=?", (msg["user_id"],)).fetchone()

    # Layer 2: Strict test-mode allowlist enforcement
    if cfg.test_mode and (not lead or lead["username"].lower() not in cfg.allowed_recipients):
        username = lead["username"] if lead else "unknown"
        return _finish(db, msg_id, "blocked",
                       f"test_mode_recipient_not_allowlisted: {username}")

    # Layer 3: Daily dispatch cap enforcement
    if _sent_today(db) >= cfg.daily_send_cap:
        return _finish(db, msg_id, "approved", "daily_cap_reached_retry_tomorrow")

    # Layer 4: Actual API dispatch with deterministic error categorization
    try:
        event_id = x_client.send_dm(lead["user_id"], msg["final_text"] or msg["draft_text"])
        return _finish(db, msg_id, "sent", "", event_id=event_id)
    except Exception as e:
        name = type(e).__name__
        err_msg = str(e)
        
        # 1. Clear block (Recipient has DMs closed / blocked / 403 Forbidden)
        if "Forbidden" in name or "403" in err_msg:
            return _finish(db, msg_id, "blocked", f"cannot_dm_recipient: {err_msg}")
            
        # 2. Rate limited (429) -> Reset to approved so operator can dispatch later
        if "TooManyRequests" in name or "429" in err_msg:
            return _finish(db, msg_id, "approved", "rate_limited_retry_later")
            
        # 3. Ambiguous failure (Timeout, 5xx, Network drop):
        # INVARIANT: NEVER auto-retry ambiguous failures. Status is set to 'failed'.
        return _finish(db, msg_id, "failed", f"ambiguous_error_no_retry: {name}: {err_msg}")

def _finish(db, msg_id, status: str, detail: str = "", event_id=None) -> SendResult:
    with tx(db):
        db.execute(
            "UPDATE messages SET status=?, status_detail=?, dm_event_id=COALESCE(?, dm_event_id), "
            "sent_at=CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP ELSE sent_at END "
            "WHERE id=?",
            (status, detail, event_id, status, msg_id),
        )
    return SendResult(status, detail)
