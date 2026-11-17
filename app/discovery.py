import json
import csv
import io
import re
from app.db import upsert_lead

SPAM_REGEX_PATTERNS = [
    r"\bairdrop\b",
    r"\bgiveaway\b",
    r"\bcrypto\s*pump\b",
    r"\b100x\b",
    r"\bfree\s*tokens\b",
    r"\bdm\s*for\s*promo\b",
    r"\bpresale\b",
    r"\bwhitelist\b",
    r"\bmemecoin\b",
    r"\bsignals?\b",
    r"\bforex\b",
    r"\baffiliate\s*link\b",
    r"\bmasterclass\b",
    r"\bcourse\s*seller\b",
]

BRAND_REGEX_PATTERNS = [
    r"\bofficial\b",
    r"\binc\.?\b",
    r"\bcorp\.?\b",
    r"\bltd\.?\b",
    r"\btechnologies\b",
    r"\bupdates\b",
    r"\bnews\b",
    r"\bdaily\b",
    r"\bdigest\b",
    r"\baggregator\b",
    r"\bbot\b",
    r"\bmagazine\b",
    r"\bmedia\b",
    r"\bportal\b",
    r"\bchannel\b",
    r"\bpress\b",
]

def build_search_query(topic: str = "") -> str:
    negative_terms = "-crypto -airdrop -giveaway -hiring -job -course -dropship -forex"
    if not topic.strip():
        return (
            '("embodied AI" OR "robot learning" OR "humanoid" OR "foundation model" '
            'OR "LLM inference") (building OR "we built" OR released OR "our paper" '
            f'OR open-source) -is:retweet -is:reply {negative_terms} lang:en'
        )
    clean_topic = re.sub(r'[^\w\s"-]', '', topic.strip())
    return f'({clean_topic}) (building OR "we built" OR released OR "open-source") -is:retweet -is:reply {negative_terms} lang:en'

def hard_filter(lead: dict) -> str | None:
    """
    Defensive rule-based pre-filter.
    Eliminates accounts with empty bios, out-of-range followers, commercial spam,
    or brand/portal identities before LLM invocation, saving API budget.
    """
    if not isinstance(lead, dict):
        return "invalid_lead_object"

    bio = lead.get("bio")
    if not bio or not isinstance(bio, str) or not bio.strip():
        return "empty_bio"

    bio_clean = bio.strip().lower()
    name = (str(lead.get("name") or "")).strip().lower()
    username = (str(lead.get("username") or "")).strip().lower()

    # Followers count defense
    raw_followers = lead.get("followers", 0)
    try:
        followers = int(raw_followers)
    except (ValueError, TypeError):
        followers = 0

    if followers < 25 or followers > 300_000:
        return f"follower_range_{followers}"

    # Spam keyword detection using word-boundary regex
    for pattern in SPAM_REGEX_PATTERNS:
        if re.search(pattern, bio_clean):
            return f"spam_keyword_{pattern.replace(r'\b', '')}"

    # Brand / Corporate portal detection
    combined_identity = f"{name} {username}"
    for pattern in BRAND_REGEX_PATTERNS:
        if re.search(pattern, combined_identity):
            return f"brand_account_{pattern.replace(r'\b', '')}"

    return None

def process_search_results(db, posts, users):
    """
    Groups tweets by author, constructs evidence JSON, runs defensive hard filter,
    and upserts into SQLite leads table.
    """
    author_tweets = {}
    for p in posts:
        aid = str(getattr(p, "author_id", ""))
        if not aid:
            continue
        tweet_data = {
            "tweet_id": str(getattr(p, "id", "")),
            "text": getattr(p, "text", ""),
            "created_at": str(getattr(p, "created_at", "")),
            "url": f"https://x.com/i/web/status/{getattr(p, 'id', '')}"
        }
        author_tweets.setdefault(aid, []).append(tweet_data)

    discovered = 0
    filtered = 0

    for aid, user_obj in users.items():
        metrics = getattr(user_obj, "public_metrics", {}) or {}
        evidence = author_tweets.get(str(aid), [])
        lead = {
            "user_id": str(aid),
            "username": getattr(user_obj, "username", "") or f"user_{aid}",
            "name": getattr(user_obj, "name", "") or "Unknown",
            "bio": getattr(user_obj, "description", "") or "",
            "location": getattr(user_obj, "location", "") or "",
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
            "profile_url": getattr(user_obj, "url", "") or f"https://x.com/{getattr(user_obj, 'username', aid)}",
            "source": "x_search",
            "evidence_json": json.dumps(evidence),
        }

        reason = hard_filter(lead)
        if reason:
            filtered += 1
            lead["status"] = "filtered_out"
            lead["filter_reason"] = reason
        else:
            discovered += 1
            lead["status"] = "discovered"
            lead["filter_reason"] = None

        upsert_lead(db, lead)

    return {"discovered": discovered, "filtered": filtered}

def import_csv_leads(db, file_content: str):
    """
    Parses CSV content safely and upserts leads with defensive fallback.
    """
    reader = csv.DictReader(io.StringIO(file_content))
    count = 0
    for row in reader:
        uid = str(row.get("user_id") or row.get("id") or "").strip()
        username = str(row.get("username") or row.get("handle") or "").strip().lstrip("@")
        if not username:
            continue
        if not uid:
            uid = f"csv_{abs(hash(username)) % 1000000}"

        sample_tweet = str(row.get("sample_tweet") or row.get("evidence") or "").strip()
        evidence = [{"tweet_id": f"tw_{uid}", "text": sample_tweet, "url": f"https://x.com/{username}/status/1"}] if sample_tweet else []

        raw_followers = row.get("followers", "100")
        try:
            followers = int(raw_followers)
        except (ValueError, TypeError):
            followers = 100

        try:
            following = int(row.get("following", 50) or 50)
        except (ValueError, TypeError):
            following = 50

        try:
            tweet_count = int(row.get("tweet_count", 10) or 10)
        except (ValueError, TypeError):
            tweet_count = 10

        lead = {
            "user_id": uid,
            "username": username,
            "name": str(row.get("name") or username).strip(),
            "bio": str(row.get("bio") or "").strip(),
            "location": str(row.get("location") or "").strip(),
            "followers": followers,
            "following": following,
            "tweet_count": tweet_count,
            "profile_url": f"https://x.com/{username}",
            "source": "csv_import",
            "evidence_json": json.dumps(evidence),
        }

        reason = hard_filter(lead)
        if reason:
            lead["status"] = "filtered_out"
            lead["filter_reason"] = reason
        else:
            lead["status"] = "discovered"
            lead["filter_reason"] = None

        upsert_lead(db, lead)
        count += 1

    return count
