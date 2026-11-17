import pytest
from app.db import init_db, upsert_lead
from app.scoring import verify_evidence, batch_score_leads, normalize_text
from app.drafting import verify_draft, verify_draft_strict
from app.llm import extract_json_from_llm
from app.discovery import hard_filter

# 1. Robust JSON Extraction Tests
def test_extract_json_from_markdown_blocks_and_syntax_flaws():
    # Markdown json block
    markdown_payload = "Here is your response:\n```json\n{\"score\": 95, \"fit\": true}\n```\nHope that helps!"
    res = extract_json_from_llm(markdown_payload)
    assert res["score"] == 95
    assert res["fit"] is True

    # Preamble text with no markdown fence
    preamble_payload = "I scored the candidate: {\"score\": 80, \"persona\": \"builder\"}"
    res2 = extract_json_from_llm(preamble_payload)
    assert res2["score"] == 80

    # Trailing comma recovery
    trailing_comma_payload = "```json\n{\"domain\": \"AI\", \"evidence\": [\"e1\", ], }\n```"
    res3 = extract_json_from_llm(trailing_comma_payload)
    assert res3["domain"] == "AI"

    # Malformed non-JSON raises ValueError cleanly
    with pytest.raises(ValueError):
        extract_json_from_llm("This is completely unparseable garbage text.")

# 2. Text Normalization & Substring Grounding Invariants
def test_verify_evidence_keeps_valid_substring():
    tweet_text = "We just released our open-source benchmark for bimanual manipulation."
    evidence_list = [{"tweet_id": "tw_101", "text": tweet_text}]
    
    scoring_result = {
        "total": 85,
        "evidence": [
            {"tweet_id": "tw_101", "quote": "open-source benchmark for bimanual manipulation"}
        ]
    }
    
    verified = verify_evidence(scoring_result, evidence_list)
    assert len(verified["evidence"]) == 1
    assert verified["total"] == 85
    assert verified["evidence"][0]["quote"] == "open-source benchmark for bimanual manipulation"

def test_verify_evidence_normalizes_curly_quotes_and_whitespace():
    # Source tweet has regular quotes, LLM returned curly quotes and extra newline
    tweet_text = 'We achieved "state of the art" on humanoid locomotion.'
    evidence_list = [{"tweet_id": "tw_102", "text": tweet_text}]
    
    scoring_result = {
        "total": 90,
        "evidence": [
            {"tweet_id": "tw_102", "quote": "achieved \n “state of the art”"}
        ]
    }
    
    verified = verify_evidence(scoring_result, evidence_list)
    assert len(verified["evidence"]) == 1
    assert verified["total"] == 90

def test_verify_evidence_strips_hallucinations():
    tweet_text = "We just released our open-source benchmark for bimanual manipulation."
    evidence_list = [{"tweet_id": "tw_101", "text": tweet_text}]
    
    scoring_result = {
        "total": 85,
        "evidence": [
            {"tweet_id": "tw_101", "quote": "we built an amazing humanoid robot that cooks breakfast"}  # Invented!
        ]
    }
    
    verified = verify_evidence(scoring_result, evidence_list)
    # The hallucinated quote must be stripped
    assert len(verified["evidence"]) == 0
    # Score capped at 40 because no valid grounded evidence remains
    assert verified["total"] <= 40
    assert "no_grounded_evidence_found" in verified["red_flags"]

def test_batch_score_leads_concurrency():
    db = init_db(":memory:")
    uids = []
    for i in range(5):
        uid = f"user_{i}"
        uids.append(uid)
        upsert_lead(db, {
            "user_id": uid, "username": f"user_{i}", "name": f"User {i}",
            "bio": "Robotics engineer building autonomous agents", "location": "Singapore",
            "followers": 500, "following": 200, "tweet_count": 50, "profile_url": "",
            "source": "test",
            "evidence_json": '[{"tweet_id": "t1", "text": "Building humanoid locomotion in Singapore"}]'
        })
    
    progress_calls = []
    def on_prog(done, total):
        progress_calls.append((done, total))

    stats = batch_score_leads(db, uids, llm_client=None, max_workers=3, on_progress=on_prog)
    assert stats["scored"] == 5
    assert stats["failed"] == 0
    assert len(progress_calls) == 5

# 3. Draft Quality & Anti-Cliche Verifier Invariants
def test_draft_verifier_catches_banned_cliches():
    evidence_list = [{"tweet_id": "tw_101", "text": "Released our VLA benchmark."}]
    
    bad_draft = {
        "text": "Hi Minh, I'm a huge fan of your work! At GenAI Fund we build AI ecosystems across Southeast Asia. We saw your open-source benchmark for bimanual manipulation and were wondering how you approach sim-to-real transfer? No worries at all if you are heads-down.",
        "evidence_tweet_id": "tw_101"
    }
    ok, reason = verify_draft(bad_draft, evidence_list)
    assert not ok
    assert "huge fan" in reason

    # Verify verify_draft_strict raises ValueError
    with pytest.raises(ValueError) as exc:
        verify_draft_strict(bad_draft, evidence_list)
    assert "huge fan" in str(exc.value)

def test_draft_verifier_requires_identity_and_valid_evidence():
    evidence_list = [{"tweet_id": "tw_101", "text": "Released our VLA benchmark."}]
    
    # Missing 'GenAI Fund'
    missing_id_draft = {
        "text": "Hi Minh, we saw your recent open-source benchmark for bimanual manipulation using lightweight VLA models. We are curious how you're approaching latency and tactile feedback on physical hardware? Feel free to ignore if you are heads-down on research.",
        "evidence_tweet_id": "tw_101"
    }
    ok, reason = verify_draft(missing_id_draft, evidence_list)
    assert not ok
    assert "GenAI Fund" in reason

    # Invalid evidence tweet id
    wrong_id_draft = {
        "text": "At GenAI Fund we follow robotics research closely across Southeast Asia. Saw your work on the VLA benchmark. How are you handling latency and tactile feedback on physical hardware? Feel free to ignore if you are heads-down.",
        "evidence_tweet_id": "fake_id_999"
    }
    ok, reason = verify_draft(wrong_id_draft, evidence_list)
    assert not ok
    assert "fake_id_999" in reason

# 4. Defensive Hard Filter Invariants
def test_hard_filter_defensive_against_nulls_and_spam():
    # Null or empty bio
    assert hard_filter({"bio": None, "followers": 100}) == "empty_bio"
    assert hard_filter({"bio": "   ", "followers": 100}) == "empty_bio"
    
    # Follower bounds
    assert "follower_range" in hard_filter({"bio": "AI dev", "followers": 10})
    assert "follower_range" in hard_filter({"bio": "AI dev", "followers": 500_000})

    # Spam keywords via regex
    assert "spam_keyword" in hard_filter({"bio": "Join our 100x crypto pump presale! DM for promo.", "followers": 500})
    
    # Brand accounts
    assert "brand_account" in hard_filter({"bio": "Building models", "name": "AI Tech News Official", "username": "ainews_bot", "followers": 500})

    # Clean candidate passes
    clean_lead = {
        "bio": "Robotics researcher at VinAI building vision-language-action models.",
        "name": "Minh Nguyen",
        "username": "minh_robotics",
        "followers": 850
    }
    assert hard_filter(clean_lead) is None
