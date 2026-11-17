# GenAI Fund — AI & Robotics Outreach Engine
> **Production-grade Forward Deployed Engineer (FDE) Prototype**  
> Automated, evidence-grounded talent discovery and personalized DM outreach on X (Twitter) for AI and robotics builders in Southeast Asia.

---

## ⚡ 5-Minute Quickstart (Evaluation Guide)

You can run and evaluate this prototype **with or without X API credentials**.

### Step 1: Clone and Set Up Environment
```bash
git clone <repo-url>
cd GenAIFund_Case
```

**MacOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
* **For Zero-Cost / Offline Evaluation:** You do **not** need to enter any API keys! Leave `.env` as default with `TEST_MODE=true`. The system includes a complete **Dry-Run / Mock Mode** and 50 realistic candidate profiles.
* **For Live X API Sending:** Fill in your X OAuth 1.0a credentials (`X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`, `X_BEARER_TOKEN`) and your `LLM_API_KEY`.

### Step 3: Run Pre-Flight Diagnostics (Optional but Recommended)
Verify environment, SQLite constraints, datasets, and API reachability in 2 seconds:
```bash
python health_check.py
```

### Step 4: Launch the UI
```bash
python -m streamlit run ui.py
# (Or: streamlit run ui.py if Python scripts are in PATH)
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## 🛡️ Core Reliability & Safety Invariants

This prototype was architected around GenAI Fund's non-negotiable operational requirements:

### 1. Absolute Zero Double-Messaging
* **Database Constraint:** The `messages` table enforces `UNIQUE(user_id)`. Attempting to insert a duplicate message raises an atomic `sqlite3.IntegrityError`.
* **Atomic Claim-Before-Send:** During message dispatch, an atomic SQL update (`UPDATE messages SET status='sending' WHERE id=? AND status='approved'`) ensures that even concurrent clicks or multiple browser tabs cannot trigger duplicate sends.

### 2. Evidence-Grounded Personalization (No AI Hallucinations)
* **Exact Substring Verifier:** The LLM is instructed to quote directly from the candidate's verified tweets or bio. The programmatic grounding verifier (`app/scoring.py::verify_evidence`) checks that every cited quote is an exact substring of raw tweets. If an LLM hallucinates an ungrounded quote, it is stripped and the candidate's score is capped at $\le 40$, preventing drafting.
* **Anti-Cliche Verifier:** Draft messages are validated (`app/drafting.py::verify_draft`) to strictly eliminate boilerplate flattery (`"huge fan"`, `"love your work"`), ensure sender identity (`"GenAI Fund"`), require an open technical question, and keep length strictly between 30–110 words.

### 3. Test-Mode Allowlist & Hard Spend Caps
* **Allowlist Enforcement:** When `TEST_MODE=true`, the engine rejects message delivery to any username not explicitly listed in `ALLOWED_RECIPIENTS`, marking the dispatch status as `blocked: test_mode_recipient_not_allowlisted`.
* **X API Budget Meter:** Every API call calculates real-time pay-per-use costs into an `audit_log`. If spend exceeds `MAX_X_SPEND_USD` (default $5.00), outbound calls are safely halted.
* **Daily Send Cap:** Hard limit of 10 DMs/day to preserve account reputation and avoid spam triggers.

### 4. High-Performance Concurrency & Deadlock Recovery
* **Concurrent Scoring:** `app/scoring.py::batch_score_leads` leverages Python's `ThreadPoolExecutor(max_workers=5)` to evaluate candidates concurrently, preventing UI freezes while maintaining SQLite transactional thread-safety.
* **Deadlock / Stuck State Recovery:** `app/sender.py::recover_stuck_messages` automatically identifies and recovers messages stuck in `sending` state (>10 minutes) on application launch, preventing permanent deadlocks if a server or process terminates unexpectedly.
* **API Rate-Limit Handling:** `app/x_client.py::safe_api_call` implements exponential backoff retry for Twitter API 429 (`TooManyRequests`) and 5xx transient server blips.

---

## 🧪 Automated Test Suite

Run unit tests verifying all core invariants:
```bash
python -m pytest -q
```
**Results:** `20 passed in 2.42s`
* `test_never_double_send`: Verifies atomic claim prevents duplicate sends.
* `test_unique_message_per_user_schema_constraint`: Verifies database-level UNIQUE constraint.
* `test_allowlist_blocks_unauthorized_recipient`: Verifies test-mode safety filter blocks non-approved users.
* `test_send_timeout_marks_failed_without_retry`: Verifies ambiguous API timeout is NEVER auto-retried.
* `test_send_forbidden_403_marks_blocked`: Verifies 403 Forbidden is marked as permanently blocked.
* `test_send_rate_limited_429_resets_approved`: Verifies 429 RateLimit safely resets to approved for later dispatch.
* `test_recover_stuck_messages_marks_failed_requiring_human_review`: Verifies deadlock crash recovery requires human review.
* `test_schema_check_constraints_prevent_garbage_status`: Verifies SQLite CHECK constraints reject invalid status.
* `test_schema_foreign_key_enforcement`: Verifies PRAGMA foreign_keys=ON rejects orphaned records.
* `test_config_fail_safe_defaults`: Verifies fail-safe defaults (TEST_MODE=True).
* `test_config_invalid_types_raise_clear_errors`: Verifies type validation on env vars.
* `test_config_negative_bounds_rejected`: Verifies negative range rejection.
* `test_extract_json_from_markdown_blocks_and_syntax_flaws`: Verifies robust JSON extraction from markdown blocks and syntax flaws.
* `test_verify_evidence_keeps_valid_substring`: Verifies valid evidence extraction.
* `test_verify_evidence_normalizes_curly_quotes_and_whitespace`: Verifies unicode quote and whitespace normalization.
* `test_verify_evidence_strips_hallucinations`: Verifies hallucinated quotes are removed and score is penalized.
* `test_batch_score_leads_concurrency`: Verifies multi-threaded concurrent scoring with progress callbacks.
* `test_draft_verifier_catches_banned_cliches`: Verifies generic cliches are blocked.
* `test_draft_verifier_requires_identity_and_valid_evidence`: Verifies sender branding and tweet ID grounding.
* `test_hard_filter_defensive_against_nulls_and_spam`: Verifies defensive hard filter handling nulls, follower bounds, and spam.

---

## 📄 Cross-Platform PDF Generation
Generate the submission one-pager PDF cleanly without any external browser or heavy OS-specific binary:
```bash
python export_pdf.py
```
*(Uses pure Python `reportlab` to compile `ONE_PAGER.pdf` natively across Windows, Linux, and macOS).*

---

## 📂 System Architecture

```
GenAIFund_Case/
├── app/
│   ├── config.py         # Type-safe configuration with safety defaults
│   ├── db.py             # SQLite schema, atomic transactions, deduplication
│   ├── x_client.py       # Tweepy v2 wrapper with real-time cost metering
│   ├── llm.py            # OpenAI-compatible client with JSON schema recovery
│   ├── discovery.py      # Recent search query builder + CSV import + hard filters
│   ├── scoring.py        # 6-criterion rubric + programmatic evidence grounding
│   ├── drafting.py       # Personalized DM prompt + anti-cliche verifier
│   ├── sender.py         # Claim-before-send state machine + allowlist guard
│   └── tracker.py        # DM event polling & unified inbox management
├── tests/
│   ├── test_core.py      # Core dedupe, unique constraint, allowlist tests
│   └── test_grounding.py # Evidence grounding & verifier test suite
├── data/
│   └── sample_leads.csv  # 8 realistic AI/robotics leads for zero-cost evaluation
├── ui.py                 # Streamlit 4-tab dashboard
├── requirements.txt      # Minimal, pinned dependencies
├── .env.example          # Safe template without secrets
└── README.md             # This guide
```

---

## 💰 Operating Cost Breakdown (100 Leads)

| Component | Operation | Calculation | Estimated Cost |
| :--- | :--- | :--- | :--- |
| **X API v2** | Recent Tweet Search | ~200 tweets returned $\times$ $0.005 | $1.00 |
| **X API v2** | User Profile Lookup | ~100 profiles $\times$ $0.010 | $1.00 |
| **X API v2** | DM Dispatch | 10–20 approved DMs $\times$ $0.015 | $0.15–$0.30 |
| **X API v2** | DM Event Polling | Manual refresh $\times$ $0.010 | $0.10 |
| **LLM Inference** | Scoring & Drafting | Small model (e.g. GPT-4o-mini / Groq) | < $0.35 |
| **Total per 100 leads** | | | **~$2.50 – $3.00** |

*(Note: In Dry-Run / CSV mode, operating cost is **$0.00**).*

---

## ⚠️ Known Limitations & Next Steps
1. **Recent Search Window:** X API pay-per-use search only accesses the previous 7 days of tweets. Builders who tweet infrequently can be reached via the CSV / seed import feature.
2. **OAuth User Context:** The current implementation uses App User Tokens (OAuth 1.0a). The next production release will introduce full OAuth 2.0 PKCE with a "Connect with X" button in the UI.
3. **Multi-User Collaboration:** Current SQLite setup is optimized for single-operator execution. For distributed teams, migrate to PostgreSQL with Row-Level Security.
