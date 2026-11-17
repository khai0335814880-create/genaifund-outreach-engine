import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  user_id TEXT PRIMARY KEY,
  username TEXT, name TEXT, bio TEXT, location TEXT,
  followers INTEGER, following INTEGER, tweet_count INTEGER,
  profile_url TEXT, source TEXT,
  evidence_json TEXT,
  status TEXT DEFAULT 'discovered' CHECK(status IN ('discovered', 'filtered_out', 'scored', 'drafted', 'approved', 'sending', 'sent', 'blocked', 'failed', 'rejected')),
  filter_reason TEXT,
  score INTEGER, score_json TEXT, fit_reason TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL UNIQUE,
  draft_text TEXT, final_text TEXT, evidence_tweet_id TEXT,
  status TEXT DEFAULT 'drafted' CHECK(status IN ('drafted', 'approved', 'sending', 'sent', 'blocked', 'failed', 'rejected')),
  status_detail TEXT, dm_event_id TEXT,
  approved_at TEXT, sent_at TEXT,
  FOREIGN KEY(user_id) REFERENCES leads(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS replies (
  event_id TEXT PRIMARY KEY,
  user_id TEXT, text TEXT, created_at TEXT,
  handled INTEGER DEFAULT 0 CHECK(handled IN (0, 1)),
  FOREIGN KEY(user_id) REFERENCES leads(user_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT CURRENT_TIMESTAMP,
  action TEXT, user_id TEXT, detail TEXT,
  cost_usd REAL DEFAULT 0
);
"""

def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path,
        check_same_thread=False,
        isolation_level=None,
        timeout=10.0
    )
    conn.row_factory = sqlite3.Row
    # Production Concurrency & Reliability PRAGMAs
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.executescript(SCHEMA)
    return conn

@contextmanager
def tx(db: sqlite3.Connection):
    """
    Atomic transaction helper using BEGIN IMMEDIATE.
    Acquires the database write lock immediately to prevent SQLITE_BUSY
    deadlocks under concurrent multithreaded writes in Streamlit.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

def upsert_lead(db, lead: dict) -> None:
    with tx(db):
        db.execute("""
        INSERT INTO leads (user_id, username, name, bio, location,
                           followers, following, tweet_count, profile_url,
                           source, evidence_json)
        VALUES (:user_id, :username, :name, :bio, :location,
                :followers, :following, :tweet_count, :profile_url,
                :source, :evidence_json)
        ON CONFLICT(user_id) DO UPDATE SET
          bio=excluded.bio, followers=excluded.followers,
          evidence_json=excluded.evidence_json
        """, lead)

def insert_message(db, user_id: str, draft_text: str, evidence_tweet_id: str):
    """
    Raises sqlite3.IntegrityError if user already has a message.
    This is the primary 'never double-message' invariant enforced at the DB schema level.
    """
    with tx(db):
        cur = db.execute(
            "INSERT INTO messages (user_id, draft_text, evidence_tweet_id) "
            "VALUES (?, ?, ?)",
            (user_id, draft_text, evidence_tweet_id),
        )
        return cur.lastrowid
