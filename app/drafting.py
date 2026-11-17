import json
import sqlite3
from app.db import tx, insert_message

SYSTEM_DRAFTING_PROMPT = """Write a personalized first Direct Message (DM) on X from GenAI Fund to the AI/robotics builder below.

Context:
GenAI Fund builds AI ecosystems in Southeast Asia. Our goal is to start a genuine peer-to-peer conversation with relevant builders, not pitch, sell, or broadcast.

Input:
You will receive the person's name, handle, bio, and specific tweets (evidence).

Rules:
1. Length: 40-80 words. Direct, warm, concise, conversational tone.
2. Structure:
   - Specific hook: Mention EXACTLY ONE specific project, paper, or detail from their evidence.
   - Who we are: Explain in one brief clause (e.g. "We're building AI ecosystems in Southeast Asia at GenAI Fund...").
   - One question: Ask ONE thoughtful, open question directly tied to what they built/researched.
   - Light opt-out: End with an easy out (e.g. "No worries at all if you're heads-down").
3. Anti-Cliche / Grounding Constraints:
   - NO emojis, NO hashtags, NO links.
   - Do NOT say: "huge fan", "love your work", "been following your journey", "impressive", "stumbled upon your profile", "excited to connect".
   - Do NOT invent familiarity or pretend we met before.
   - Reference the exact tweet_id used in your evidence hook.

EXAMPLES:
Bad (Too generic, empty flattery, banned phrase):
"Hi John, I'm a huge fan of your work in AI! I've been following your journey and love what you are building. We at GenAI Fund build AI ecosystems in SEA. Would love to connect and chat about your roadmap. Let me know when you have time!"

Good (Specific hook, grounded evidence, open technical question, polite opt-out):
"Hi Minh, saw your recent release of the open-source VLA benchmark for bimanual manipulation. At GenAI Fund, we're supporting AI and robotics builders across Southeast Asia. Curious how you're approaching latency and tactile feedback on physical hardware? No worries at all if you're currently heads-down on research."

Output JSON:
{
  "text": "<DM text>",
  "evidence_tweet_id": "<tweet_id>"
}
"""

BANNED_PHRASES = [
    "huge fan", "love your work", "been following", "came across your profile",
    "stumbled upon", "impressive work", "blown away", "excited to connect",
    "honored to", "kudos to", "amazing journey"
]

def verify_draft(draft_data: dict, evidence_list: list) -> tuple[bool, str]:
    """Validates draft constraints, returning (is_valid, failure_reason)."""
    text = (draft_data.get("text") or "").strip()
    words = len(text.split())
    if words < 30 or words > 110:
        return False, f"Length {words} words outside allowed range (30-110)"

    lower_text = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower_text:
            return False, f"Generic or insincere phrase found: '{phrase}'"

    if "genai fund" not in lower_text:
        return False, "Identity 'GenAI Fund' not stated in message"

    ev_id = str(draft_data.get("evidence_tweet_id", ""))
    valid_ids = {str(t.get("tweet_id")) for t in evidence_list}
    if valid_ids and ev_id not in valid_ids:
        return False, f"Evidence tweet ID '{ev_id}' not found in candidate evidence"

    # Must contain an open question
    if "?" not in text:
        return False, "Must include an open question"

    return True, ""

def verify_draft_strict(draft_data: dict, evidence_list: list) -> None:
    """
    Strict validation raising ValueError.
    Replaces bare asserts so constraints remain active even when python is run with -O.
    """
    ok, reason = verify_draft(draft_data, evidence_list)
    if not ok:
        raise ValueError(reason)

def generate_draft(db, user_id: str, llm_client) -> dict:
    lead = db.execute("SELECT * FROM leads WHERE user_id=?", (user_id,)).fetchone()
    if not lead:
        raise ValueError(f"Lead {user_id} not found")

    # Check if a message already exists (prevent duplicate drafting)
    existing = db.execute("SELECT * FROM messages WHERE user_id=?", (user_id,)).fetchone()
    if existing:
        return {
            "status": "already_exists",
            "message_id": existing["id"],
            "draft_text": existing["draft_text"],
            "evidence_tweet_id": existing["evidence_tweet_id"],
        }

    try:
        evidence_list = json.loads(lead["evidence_json"] or "[]")
    except Exception:
        evidence_list = []

    user_prompt = f"""Recipient:
Name: {lead['name']} (@{lead['username']})
Bio: {lead['bio']}
Location: {lead['location']}
Fit reason from assessment: {lead['fit_reason']}

Available Evidence Tweets:
"""
    for ev in evidence_list:
        user_prompt += f"Tweet ID {ev.get('tweet_id')}: {ev.get('text')}\n"

    last_error = ""
    # Multi-turn Self-Correction Loop (Up to 3 attempts with explicit feedback)
    for attempt in range(3):
        res = llm_client.complete_json(SYSTEM_DRAFTING_PROMPT, user_prompt)
        try:
            verify_draft_strict(res, evidence_list)
            draft_text = res["text"].strip()
            ev_id = str(res.get("evidence_tweet_id", ""))
            try:
                msg_id = insert_message(db, user_id, draft_text, ev_id)
                with tx(db):
                    db.execute("UPDATE leads SET status='drafted' WHERE user_id=?", (user_id,))
                return {
                    "status": "success",
                    "message_id": msg_id,
                    "draft_text": draft_text,
                    "evidence_tweet_id": ev_id,
                }
            except sqlite3.IntegrityError:
                return {"status": "blocked", "reason": "user_already_has_message"}
        except ValueError as e:
            last_error = str(e)
            user_prompt += (
                f"\n[CRITICAL CORRECTION REQUIRED - Attempt {attempt+1}] "
                f"Your previous draft failed verification: '{last_error}'. "
                f"Please rewrite the text strictly following the 40-80 words rule, "
                f"explicitly include 'GenAI Fund', cite the valid tweet_id, and remove all banned phrases.\n"
            )

    return {"status": "needs_manual", "reason": f"Failed verification after 3 attempts: {last_error}"}
