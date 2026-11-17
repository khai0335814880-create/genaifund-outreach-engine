# GenAI Fund — Forward Deployed Engineer (FDE) Write-up
**Project:** AI & Robotics Talent Discovery & Evidence-Grounded Outreach Engine  
**Author:** Khai Nguyen (FDE Candidate)  
**Date:** November 2026  

---

### 1. Executive Summary & Approach
GenAI Fund requires a reliable, usable tool to discover AI and robotics builders in Southeast Asia, draft warm and evidence-grounded outreach messages, and initiate genuine peer conversations without spamming or double-messaging.

Rather than orchestrating fragile no-code workflows (e.g. n8n) or building a slide deck mockup, I engineered a **code-first, human-in-the-loop web application** using **Python, Streamlit, and SQLite**. The pipeline implements a 6-stage architecture:
1. **Targeted Discovery:** Query builder for X API v2 recent search (`-is:retweet -is:reply lang:en`) combined with zero-cost CSV/seed import.
2. **Hard Pre-filtering:** Rule-based heuristics to eliminate empty profiles, bot farms, brands, and crypto spam before LLM invocation.
3. **Evidence-Grounded Scoring:** A deterministic 6-dimension rubric (0–100) that extracts exact substrings from tweets/bios.
4. **Anti-Cliche Drafting:** Constrained LLM prompts generating 40–80 word conversational drafts citing exactly one verified tweet.
5. **Safe Dispatch Engine:** Two-layer duplicate prevention (`UNIQUE(user_id)` constraint + atomic `claim-before-send` transaction), test-mode allowlist, and budget meters.
6. **Unified Tracking & Inbox:** Manual poll-based event sync matching incoming DMs to previous outbound outreach.

---

### 2. Measured Results & Verification

| Evaluation Metric | Measured Result | Benchmark / Verification Method |
| :--- | :--- | :--- |
| **Setup Time** | **< 5 minutes** | Clean environment clone, zero-config mock mode with 50 diverse candidates. |
| **Automated Unit Tests** | **20 / 20 Passed (2.42s)** | Full coverage of ACID transactions, WAL mode, robust JSON parsing, and grounding verifiers. |
| **Precision @ 20 Leads** | **85% (17 / 20 relevant)** | Manual labeling of top 20 candidate profiles on AI/Robotics fit. |
| **Grounding Verification** | **100% Substring Accuracy** | Synthetic injection of hallucinated quotes was 100% detected and penalized. |
| **Duplicate Message Rate** | **0.00% (Strict Zero)** | Verified via concurrent double-dispatch tests and SQLite unique constraints. |

---

### 3. Engineering Trade-offs & Platform Compliance

* **Code-first vs. No-Code (n8n):** While n8n allows rapid API chaining, it struggles with atomic locking, custom approval side-by-side editing, and local state management. Python + SQLite provides battle-tested ACID transactions, easy programmatic unit testing, and complete developer autonomy.
* **OAuth 1.0a User Tokens vs. OAuth 2.0 PKCE:** Selected OAuth 1.0a app user tokens for the prototype. This avoided complex redirect callback servers while allowing immediate out-of-the-box evaluation by the GenAI Fund team.
* **7-Day Recent Search Window:** Under X's pay-per-use model, full-archive search is economically prohibitive. I accommodated this by providing a zero-cost CSV/seed import module to ingest researchers who post infrequently.
* **Ambiguous Failure Handling:** If an API dispatch encounters an unknown 5xx timeout, the system classifies the status as `failed` rather than triggering an auto-retry loop. In outbound outreach, avoiding duplicate messages to VIP candidates is strictly more important than guaranteed delivery on the first attempt.
* **Platform Terms & Rate Limits:** No unauthorized web scraping or reverse-engineered private endpoints were used. All interactions strictly utilize official X API v2 endpoints with human approval required for every single message.

---

### 4. Financial Economics (100 Leads Scanned)
* **X API v2:** Search (~200 tweets @ $0.005 = $1.00) + User lookup (~100 users @ $0.010 = $1.00) + DM sends (~15 DMs @ $0.015 = $0.22) + Polling ($0.10) $\approx$ **$2.32**.
* **LLM Inference:** Small hosted model (e.g., GPT-4o-mini / Claude 3.5 Haiku) for JSON scoring and 15 drafts $\approx$ **$0.25**.
* **Total Operating Cost:** **~$2.50 to $2.80 per 100-lead outreach cycle**.

---

### 5. Intentional AI Usage & Validation
* **What AI Generated:** Scaffolding boilerplate, CSS layout helpers, and regex string manipulation.
* **What I Authored & Governed:** The scoring rubric, the SQL state machine, atomic claim transactions, safety allowlist constraints, and pytest suites.
* **Validation Strategy:** I manually labeled 20 profiles, refined the system prompts against real-world ambiguous cases (e.g. explicitly grounding Southeast Asia geographic claims), and implemented programmatic post-processors that parse and verify LLM outputs before they touch the database.

---

### 6. Roadmap & Future Scope
1. **Full OAuth 2.0 PKCE Flow:** One-click account authorization for multi-seat operator teams.
2. **Multi-Source Sourcing:** Ingesting authors directly from ArXiv papers, GitHub repositories, and Southeast Asia tech conferences, auto-matching to X profiles.
3. **Adaptive Draft Learning:** Utilizing reply feedback (positive/neutral/opt-out) to continually optimize prompt questions.
