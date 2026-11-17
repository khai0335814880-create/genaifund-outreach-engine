import time
import tweepy
from tweepy.errors import TooManyRequests, TwitterServerError
from app.db import tx

# Approx prices (verify at console.x.com before final submission)
PRICE_TWEET_READ = 0.005
PRICE_USER_READ = 0.010
PRICE_DM_SEND = 0.015
PRICE_DM_EVENT = 0.010

class BudgetExceeded(RuntimeError): pass

def safe_api_call(func, *args, max_retries: int = 3, initial_delay: float = 2.0, **kwargs):
    """
    Executes a tweepy API call with exponential backoff for rate limits (429)
    and transient server errors (5xx).
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except TooManyRequests as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
        except TwitterServerError as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
        except Exception:
            raise

class XClient:
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db
        self.client = tweepy.Client(
            bearer_token=cfg.x_bearer_token or None,
            consumer_key=cfg.x_api_key or None,
            consumer_secret=cfg.x_api_secret or None,
            access_token=cfg.x_access_token or None,
            access_token_secret=cfg.x_access_secret or None,
            wait_on_rate_limit=False,
        )

    def _charge(self, action: str, usd: float, detail: str = ""):
        with tx(self.db):
            self.db.execute(
                "INSERT INTO audit_log (action, detail, cost_usd) VALUES (?, ?, ?)",
                (action, detail, usd),
            )
            total = self.db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM audit_log"
            ).fetchone()[0]
        if total > self.cfg.max_x_spend_usd:
            raise BudgetExceeded(f"X spend ${total:.2f} > cap ${self.cfg.max_x_spend_usd}")

    def health_check(self) -> dict:
        me = safe_api_call(self.client.get_me, user_fields=["username", "public_metrics"])
        if not me or not me.data:
            return {"status": "error", "message": "Failed to fetch user"}
        return {"id": str(me.data.id), "username": me.data.username}

    def search_recent(self, query: str, max_results: int = 50):
        r = safe_api_call(
            self.client.search_recent_tweets,
            query=query, max_results=max_results,
            tweet_fields=["created_at", "public_metrics", "author_id"],
            expansions=["author_id"],
            user_fields=["description", "location", "public_metrics", "url"],
        )
        posts = r.data or []
        self._charge("x.search", PRICE_TWEET_READ * len(posts), query[:60])
        users = {str(u.id): u for u in (r.includes or {}).get("users", [])}
        if users:
            self._charge("x.user_read_bundle", PRICE_USER_READ * len(users))
        return posts, users

    def get_user(self, username: str):
        r = safe_api_call(
            self.client.get_user,
            username=username,
            user_fields=["description", "location", "public_metrics", "url"],
        )
        self._charge("x.user_read", PRICE_USER_READ, username)
        return r.data

    def send_dm(self, participant_id: str, text: str):
        r = safe_api_call(
            self.client.create_direct_message,
            participant_id=participant_id, text=text
        )
        self._charge("x.dm_send", PRICE_DM_SEND, participant_id)
        event_id = getattr(r.data, "dm_event_id", None) or getattr(r.data, "id", None)
        return str(event_id) if event_id else None

    def list_dm_events(self, max_results: int = 15):
        r = safe_api_call(
            self.client.get_direct_message_events,
            event_types="MessageCreate",
            dm_event_fields=["created_at", "sender_id", "text"],
            max_results=max_results,
        )
        events = r.data or []
        self._charge("x.dm_read", PRICE_DM_EVENT * len(events))
        return events

    def total_spent(self) -> float:
        return self.db.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM audit_log"
        ).fetchone()[0]
