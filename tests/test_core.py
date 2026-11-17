import os
import sqlite3
import pytest
from app.db import init_db, upsert_lead, insert_message
from app.sender import send_message, recover_stuck_messages, SendResult
from app.config import Config, ConfigError

@pytest.fixture
def db():
    d = init_db(":memory:")
    for uid, u in [("1", "alice"), ("2", "bob"), ("3", "stranger")]:
        upsert_lead(d, {
            "user_id": uid, "username": u, "name": u, "bio": "x",
            "location": "", "followers": 100, "following": 100,
            "tweet_count": 50, "profile_url": "", "source": "test",
            "evidence_json": "[]",
        })
    return d

@pytest.fixture
def cfg():
    return Config(
        x_api_key="", x_api_secret="", x_access_token="",
        x_access_secret="", x_bearer_token="",
        llm_api_key="", llm_model="m", llm_base_url=None,
        test_mode=True,
        allowed_recipients={"alice", "bob"},
        daily_send_cap=10, send_delay_min_s=0, send_delay_max_s=0,
        max_x_spend_usd=100, db_path=":memory:",
    )

class FakeXClient:
    """Deterministic offline test double simulating X API v2 responses and errors."""
    def __init__(self, should_fail: bool = False, fail_exception: Exception = None):
        self.calls = 0
        self.should_fail = should_fail
        self.fail_exception = fail_exception or RuntimeError("Simulated network failure")

    def send_dm(self, participant_id: str, text: str):
        self.calls += 1
        if self.should_fail:
            raise self.fail_exception
        return f"mock_dm_evt_{self.calls}"

def _make_approved_msg(db, uid: str) -> int:
    mid = insert_message(db, uid, "Hello, exploring AI in SEA.", "ev_tweet_1")
    db.execute("UPDATE messages SET status='approved', final_text='Hello, exploring AI in SEA.' WHERE id=?", (mid,))
    return mid

# 1. State Machine & Deduplication Invariants
def test_never_double_send(db, cfg):
    fake = FakeXClient()
    mid = _make_approved_msg(db, "1")
    r1 = send_message(db, fake, cfg, mid)
    r2 = send_message(db, fake, cfg, mid)
    assert r1.is_success
    assert r1.status == "sent"
    assert r2.status == "blocked"
    assert "already_claimed" in r2.reason
    assert fake.calls == 1  # Strictly 1 API call, never duplicated

def test_unique_message_per_user_schema_constraint(db):
    insert_message(db, "1", "hi", "ev")
    with pytest.raises(sqlite3.IntegrityError):
        insert_message(db, "1", "hi again", "ev")

def test_allowlist_blocks_unauthorized_recipient(db, cfg):
    fake = FakeXClient()
    mid = _make_approved_msg(db, "3")  # 'stranger' is not in allowed_recipients {'alice', 'bob'}
    r = send_message(db, fake, cfg, mid)
    assert r.status == "blocked"
    assert "test_mode_recipient_not_allowlisted" in r.reason
    assert fake.calls == 0

# 2. Crash & Network Error Handling Invariants
def test_send_timeout_marks_failed_without_retry(db, cfg):
    """
    CRITICAL TEST: If external API times out (ambiguous state), system MUST mark
    as 'failed' and NEVER auto-retry to prevent sending duplicate DMs to VIPs.
    """
    fake = FakeXClient(should_fail=True, fail_exception=TimeoutError("Connection to api.twitter.com timed out"))
    mid = _make_approved_msg(db, "1")
    
    res = send_message(db, fake, cfg, mid)
    assert res.status == "failed"
    assert "ambiguous_error_no_retry" in res.reason
    assert fake.calls == 1  # Exactly 1 call, zero blind retries
    
    # DB state must reflect 'failed'
    row = db.execute("SELECT status, status_detail FROM messages WHERE id=?", (mid,)).fetchone()
    assert row["status"] == "failed"
    assert "TimeoutError" in row["status_detail"]

def test_send_forbidden_403_marks_blocked(db, cfg):
    class FakeForbidden(Exception): pass
    fake = FakeForbidden("403 Forbidden: Recipient does not accept direct messages from you.")
    client = FakeXClient(should_fail=True, fail_exception=fake)
    mid = _make_approved_msg(db, "1")
    
    res = send_message(db, client, cfg, mid)
    assert res.status == "blocked"
    assert "cannot_dm_recipient" in res.reason
    assert client.calls == 1

def test_send_rate_limited_429_resets_approved(db, cfg):
    class FakeTooManyRequests(Exception): pass
    fake = FakeTooManyRequests("429 Too Many Requests: Rate limit exceeded.")
    client = FakeXClient(should_fail=True, fail_exception=fake)
    mid = _make_approved_msg(db, "1")
    
    res = send_message(db, client, cfg, mid)
    assert res.status == "approved"
    assert "rate_limited_retry_later" in res.reason
    
    row = db.execute("SELECT status FROM messages WHERE id=?", (mid,)).fetchone()
    assert row["status"] == "approved"

def test_recover_stuck_messages_marks_failed_requiring_human_review(db):
    mid = insert_message(db, "1", "hello", "ev_tweet")
    # Simulate a crash where process died while status was 'sending' 10 minutes ago
    db.execute("UPDATE messages SET status='sending', approved_at=datetime('now', '-600 seconds') WHERE id=?", (mid,))
    
    recovered = recover_stuck_messages(db, timeout_seconds=300)
    assert recovered == 1
    
    row = db.execute("SELECT status, status_detail FROM messages WHERE id=?", (mid,)).fetchone()
    assert row["status"] == "failed"
    assert "Manual verification required" in row["status_detail"]

# 3. Database Schema Integrity & PRAGMA Invariants
def test_schema_check_constraints_prevent_garbage_status(db):
    with pytest.raises(sqlite3.IntegrityError):
        # Attempt to insert an invalid status violating CHECK constraint
        db.execute("INSERT INTO messages (user_id, draft_text, status) VALUES ('99', 'test', 'hacked_status')")

def test_schema_foreign_key_enforcement(db):
    with pytest.raises(sqlite3.IntegrityError):
        # Attempt to insert message for non-existent lead user_id
        db.execute("INSERT INTO messages (user_id, draft_text) VALUES ('non_existent_user_999', 'hello')")

# 4. Config Validation Tests
def test_config_fail_safe_defaults(monkeypatch):
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("DAILY_SEND_CAP", raising=False)
    monkeypatch.delenv("MAX_X_SPEND_USD", raising=False)
    
    cfg = Config.load()
    assert cfg.test_mode is True
    assert cfg.daily_send_cap == 10
    assert cfg.max_x_spend_usd == 5.0

def test_config_invalid_types_raise_clear_errors(monkeypatch):
    monkeypatch.setenv("DAILY_SEND_CAP", "mười_tin")
    with pytest.raises(ConfigError) as exc:
        Config.load()
    assert "Invalid integer value" in str(exc.value)

    monkeypatch.setenv("DAILY_SEND_CAP", "10")
    monkeypatch.setenv("MAX_X_SPEND_USD", "năm_đô")
    with pytest.raises(ConfigError) as exc:
        Config.load()
    assert "Invalid numeric value" in str(exc.value)

    monkeypatch.setenv("MAX_X_SPEND_USD", "5.0")
    monkeypatch.setenv("TEST_MODE", "maybe")
    with pytest.raises(ConfigError) as exc:
        Config.load()
    assert "Invalid boolean value" in str(exc.value)

def test_config_negative_bounds_rejected(monkeypatch):
    monkeypatch.setenv("DAILY_SEND_CAP", "-5")
    with pytest.raises(ConfigError) as exc:
        Config.load()
    assert "DAILY_SEND_CAP" in str(exc.value)
