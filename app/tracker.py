from app.db import tx

def refresh_replies(db, x_client, my_id: str = "", max_results: int = 15) -> dict:
    """
    Polls DM events from X API with checkpoint optimization.
    Restricts default max_results to 15 (capping cost to ~$0.15 instead of $0.50 per click).
    Filters out previously processed event IDs to prevent duplicate database operations.
    """
    events = x_client.list_dm_events(max_results=max_results)
    new_replies = 0

    # Checkpoint: cache recent event_ids already in database
    recorded_ids = {
        r[0] for r in db.execute("SELECT event_id FROM replies ORDER BY created_at DESC LIMIT 50").fetchall()
    }

    with tx(db):
        for ev in events:
            event_id = str(getattr(ev, "id", "") or getattr(ev, "dm_event_id", "") or "")
            if not event_id or event_id in recorded_ids:
                continue

            sender_id = str(getattr(ev, "sender_id", "") or "")
            if my_id and sender_id == str(my_id):
                continue  # Skip our own outgoing messages

            text = getattr(ev, "text", "") or ""
            created_at = str(getattr(ev, "created_at", "") or "")

            # Only track replies from users we have officially contacted
            sent_msg = db.execute("SELECT id FROM messages WHERE user_id=?", (sender_id,)).fetchone()
            if sent_msg:
                cur = db.execute("""
                    INSERT OR IGNORE INTO replies (event_id, user_id, text, created_at, handled)
                    VALUES (?, ?, ?, ?, 0)
                """, (event_id, sender_id, text, created_at))
                if cur.rowcount > 0:
                    new_replies += 1
                    recorded_ids.add(event_id)

    return {"total_events_scanned": len(events), "new_replies": new_replies}

def mark_reply_handled(db, event_id: str) -> None:
    with tx(db):
        db.execute("UPDATE replies SET handled=1 WHERE event_id=?", (event_id,))

def get_inbox_items(db):
    """
    Retrieves all replies with associated lead profile and sent message context.
    """
    query = """
    SELECT r.event_id, r.user_id, r.text as reply_text, r.created_at as reply_time, r.handled,
           l.username, l.name, l.bio,
           m.final_text, m.sent_at
    FROM replies r
    JOIN leads l ON r.user_id = l.user_id
    LEFT JOIN messages m ON r.user_id = m.user_id
    ORDER BY r.handled ASC, r.created_at DESC
    """
    return db.execute(query).fetchall()
