import streamlit as st
import time
import json
import os
import sqlite3
import pandas as pd
from app.config import Config
from app.db import init_db, tx, upsert_lead, insert_message
from app.x_client import XClient, BudgetExceeded
from app.llm import LLMClient
from app.discovery import build_search_query, process_search_results, import_csv_leads, hard_filter
from app.scoring import score_lead, verify_evidence, batch_score_leads
from app.drafting import generate_draft, verify_draft
from app.sender import send_message, _sent_today, recover_stuck_messages
from app.tracker import refresh_replies, mark_reply_handled, get_inbox_items

# Streamlit Page Config
st.set_page_config(
    page_title="GenAI Fund — AI & Robotics Outreach Engine",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Enterprise B2B Design System (Linear / Stripe Inspired)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
    }
    
    .stApp {
        background-color: #F9FAFB !important;
    }

    /* Fixed Top App Header */
    div[data-testid="stDecoration"] {
        display: none !important;
    }
    .stAppDeployButton, [data-testid="stAppDeployButton"] {
        display: none !important;
    }
    header[data-testid="stHeader"] {
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        border-bottom: 1px solid #E2E8F0 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
        height: 3.5rem !important;
        z-index: 999990 !important;
    }
    header[data-testid="stHeader"]::before {
        content: "GenAI Fund \u2014 AI & Robotics Outreach Engine \u00a0\u00a0\u2022\u00a0\u00a0 FDE Prototype";
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        color: #0F172A !important;
        letter-spacing: -0.015em !important;
        margin-left: 2rem !important;
        white-space: nowrap !important;
    }
    .block-container {
        padding-top: 4.8rem !important;
        padding-bottom: 2.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }

    /* Enterprise Metric Cards */
    [data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        padding: 12px 16px !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        color: #64748B !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.38rem !important;
        font-weight: 700 !important;
        color: #0F172A !important;
        letter-spacing: -0.02em !important;
        white-space: nowrap !important;
        overflow: visible !important;
        line-height: 1.25 !important;
    }
    /* Hide meaningless green delta up-arrows */
    [data-testid="stMetricDelta"] svg {
        display: none !important;
    }
    [data-testid="stMetricDelta"] {
        display: inline-block !important;
        font-size: 0.74rem !important;
        font-weight: 500 !important;
        background-color: #F1F5F9 !important;
        color: #475569 !important;
        border-radius: 4px !important;
        padding: 2px 8px !important;
        margin-top: 4px !important;
        border: 1px solid #E2E8F0 !important;
    }

    /* Toggle switches - Active State is Enterprise Emerald Green */
    div[data-testid="stToggle"] > label > div[data-baseweb="checkbox"] > div[aria-checked="true"],
    div[data-testid="stToggle"] [aria-checked="true"],
    div[data-testid="stToggle"] div[role="switch"][aria-checked="true"],
    div[data-testid="stToggle"] input:checked ~ div {
        background-color: #10B981 !important;
        border-color: #10B981 !important;
    }
    div[data-testid="stToggle"] > label > div[data-baseweb="checkbox"] > div[aria-checked="true"] > div,
    div[data-testid="stToggle"] div[role="switch"][aria-checked="true"] div {
        background-color: #FFFFFF !important;
    }

    /* Technical Monospace Formatting for Search Query Textarea */
    div[data-testid="stTextArea"] textarea {
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace !important;
        font-size: 0.82rem !important;
        background-color: #F8FAFC !important;
        color: #1E293B !important;
        line-height: 1.45 !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 6px !important;
    }

    /* Primary CTA Buttons - Enterprise Indigo */
    button[kind="primary"] {
        background-color: #4F46E5 !important;
        border-color: #4338CA !important;
        color: #FFFFFF !important;
        font-weight: 500 !important;
        font-size: 0.88rem !important;
        border-radius: 6px !important;
        box-shadow: 0 1px 2px rgba(79, 70, 229, 0.25) !important;
        transition: all 0.15s ease-in-out !important;
    }
    button[kind="primary"]:hover {
        background-color: #4338CA !important;
        border-color: #3730A3 !important;
    }

    /* Secondary Buttons */
    button[kind="secondary"] {
        background-color: #FFFFFF !important;
        border: 1px solid #D1D5DB !important;
        color: #374151 !important;
        font-weight: 500 !important;
        font-size: 0.88rem !important;
        border-radius: 6px !important;
    }
    button[kind="secondary"]:hover {
        background-color: #F3F4F6 !important;
        border-color: #9CA3AF !important;
        color: #111827 !important;
    }

    /* Slider accent color */
    div[data-testid="stSlider"] div[role="slider"] {
        background-color: #4F46E5 !important;
    }

    /* Clean Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 1px solid #E2E8F0;
        margin-bottom: 1.1rem;
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        color: #64748B !important;
        border-radius: 6px 6px 0 0 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #4F46E5 !important;
        border-bottom: 2px solid #4F46E5 !important;
    }
    
    /* Option Card Styling */
    .option-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.5rem;
    }
    .option-badge-recommended {
        font-size: 0.72rem;
        font-weight: 600;
        color: #065F46;
        background-color: #D1FAE5;
        padding: 2px 8px;
        border-radius: 4px;
        border: 1px solid #A7F3D0;
    }
    .option-badge-api {
        font-size: 0.72rem;
        font-weight: 600;
        color: #1E40AF;
        background-color: #DBEAFE;
        padding: 2px 8px;
        border-radius: 4px;
        border: 1px solid #BFDBFE;
    }

    /* Divider */
    hr {
        margin-top: 0.9rem !important;
        margin-bottom: 0.9rem !important;
        border-color: #E2E8F0 !important;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Session State
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False

# Initialize Config & Database
@st.cache_resource
def get_resources():
    cfg = Config.load()
    db = init_db(cfg.db_path)
    recovered = recover_stuck_messages(db, timeout_seconds=300)
    return cfg, db, recovered

cfg, db, recovered_on_startup = get_resources()

daily_sent = _sent_today(db)
total_spend = db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM audit_log").fetchone()[0]
unhandled_count = db.execute("SELECT COUNT(*) FROM replies WHERE handled=0").fetchone()[0]

# Sidebar: Controls & System Diagnostics
with st.sidebar:
    st.markdown("### System Controls")
    
    mock_mode = st.toggle("Dry Run / Mock Mode", value=not bool(cfg.x_api_key), help="Simulates external X API actions without spending real credits.")
    test_mode = st.toggle("Test Mode (Allowlist Only)", value=cfg.test_mode, help="When ON, strictly restricts outbound sends to ALLOWED_RECIPIENTS.")
    
    allowed_list = list(cfg.allowed_recipients)
    if allowed_list:
        st.caption(f"**Allowed Recipients ({len(allowed_list)}):** {', '.join(allowed_list)}")
    else:
        st.caption("**Allowed Recipients (0):** None (All sends blocked in Test Mode)")
    
    st.divider()
    with st.expander("Service Diagnostics", expanded=True):
        st.caption(f"**LLM Model:** `{cfg.llm_model}`")
        st.caption(f"**LLM Gateway:** {'Active (API Key loaded)' if cfg.llm_api_key else 'Offline Grounded Mock'}")
        
        if cfg.x_api_key:
            try:
                x_test = XClient(cfg, db)
                st.caption("**X API Client:** Authenticated (OAuth 1.0a)")
            except Exception as e:
                st.caption(f"**X API Client:** Connection Error ({e})")
        else:
            st.caption("**X API Client:** Mock Dispatch Mode (Zero Cost)")
            
        st.caption(f"**Daily Quota:** {daily_sent} / {cfg.daily_send_cap} DMs sent")
        st.caption(f"**Spend Ceiling:** ${total_spend:.2f} / ${cfg.max_x_spend_usd:.2f}")

    with st.expander("Reset Demo Environment", expanded=False):
        st.caption("Clears all cached leads, outbox messages, and replies for a fresh demo walkthrough.")
        if st.button("Reset Database (Fresh Run)", type="secondary", disabled=st.session_state.is_processing):
            with tx(db):
                db.execute("DELETE FROM replies")
                db.execute("DELETE FROM messages")
                db.execute("DELETE FROM leads")
                db.execute("DELETE FROM audit_log")
            st.toast("Database cleared successfully")
            st.rerun()

    if recovered_on_startup:
        st.warning(f"Recovered {recovered_on_startup} stuck message(s) from previous session (marked as failed for safety).")


# Live Mode Safety Warning Banner
if not test_mode:
    st.warning("⚠️ Warning: Live Outreach Mode is ACTIVE. Outbound messages will be sent to real external X accounts. Verify all drafts carefully before approving.")

# Resource exhaustion flags
budget_exhausted = (total_spend >= cfg.max_x_spend_usd)
daily_cap_reached = (daily_sent >= cfg.daily_send_cap)

# Top Status Dashboard (4 Clean Cards)
col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
col_stat1.metric("Execution Mode", "Test Mode (Safe)" if cfg.test_mode else "Live Outreach", "Allowlist active" if cfg.test_mode else "Unrestricted")
col_stat2.metric("Daily DM Cap", f"{daily_sent} / {cfg.daily_send_cap}", "DMs dispatched today")
col_stat3.metric("X API Spend", f"${total_spend:.2f}", f"Ceiling: ${cfg.max_x_spend_usd:.2f}", delta_color="off")
col_stat4.metric("Pending Replies", f"{unhandled_count}", "Awaiting review" if unhandled_count else "All caught up")

st.divider()

# Tab Navigation (No Emojis, Pure Text)
tab1, tab2, tab3, tab4 = st.tabs([
    "Find & Discover",
    "Candidate Scoring",
    "Review & Approvals",
    "Outbox & Tracking"
])

# ==========================================
# TAB 1: FIND & DISCOVER
# ==========================================
with tab1:
    col_left, col_right = st.columns([1, 1])

    # Option 1: Seed & CSV Import (RECOMMENDED - Displayed FIRST on the Left)
    with col_left:
        with st.container(border=True):
            st.markdown("""
            <div class="option-card-header">
                <span style="font-size: 1.05rem; font-weight: 700; color: #0F172A;">Option 1: CSV & Dataset Import</span>
                <span class="option-badge-recommended">RECOMMENDED FOR ZERO-COST TEST</span>
            </div>
            """, unsafe_allow_html=True)
            st.caption("Evaluate the full pipeline with 50 realistic SEA candidate profiles without incurring X API costs.")
            
            sample_path = os.path.join(os.path.dirname(__file__), "data", "sample_leads.csv")
            if st.button("Load Pre-built Dataset (50 SEA Leads)", type="primary", disabled=st.session_state.is_processing):
                st.session_state.is_processing = True
                try:
                    with st.spinner("Importing 50 sample profiles and applying hard heuristics..."):
                        with open(sample_path, "r", encoding="utf-8") as f:
                            count = import_csv_leads(db, f.read())
                    st.toast(f"Imported {count} realistic candidate profiles")
                    st.success(f"Successfully ingested and indexed {count} candidate profiles.")
                    st.rerun()
                finally:
                    st.session_state.is_processing = False

            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            uploaded_csv = st.file_uploader("Upload custom candidate CSV", type=["csv"], help="Upload CSV containing user_id, username, name, bio, location, sample_tweet.")
            if uploaded_csv:
                try:
                    content = uploaded_csv.getvalue().decode("utf-8")
                    if not content.strip():
                        st.error("Uploaded CSV file is completely empty. Please select a valid CSV.")
                    else:
                        imported = import_csv_leads(db, content)
                        if imported > 0:
                            st.toast(f"Imported {imported} leads from CSV")
                            st.success(f"Successfully processed {imported} leads from uploaded file.")
                            st.rerun()
                        else:
                            st.error("No valid candidate rows found. Please ensure the CSV contains 'username' and 'bio' columns.")
                except UnicodeDecodeError:
                    st.error("Encoding error: File must be a valid UTF-8 formatted CSV.")
                except Exception as e:
                    st.error(f"Error parsing uploaded CSV: {e}")

            st.caption("Schema requirements: user_id, username, name, bio, location, followers, sample_tweet.")
            st.caption("All imported profiles are automatically deduplicated against existing database records.")

    # Option 2: Live X Search (API v2) (Displayed on the Right)
    with col_right:
        with st.container(border=True):
            st.markdown("""
            <div class="option-card-header">
                <span style="font-size: 1.05rem; font-weight: 700; color: #0F172A;">Option 2: Live X Search</span>
                <span class="option-badge-api">PAY-PER-USE API</span>
            </div>
            """, unsafe_allow_html=True)
            default_query = build_search_query()
            query_input = st.text_area("Search Query (X API v2)", value=default_query, height=68)
            max_results = st.slider("Max Tweets to Scan", min_value=10, max_value=100, value=20, step=10, help="Controls search depth and X API recent search cost.")
            
            if budget_exhausted:
                st.warning(f"Spend ceiling reached (${total_spend:.2f} / ${cfg.max_x_spend_usd:.2f}). Live queries are safely paused.")

            if st.button("Execute Live Search (X API)", type="secondary", disabled=(budget_exhausted or st.session_state.is_processing)):
                st.session_state.is_processing = True
                try:
                    if mock_mode or not cfg.x_api_key:
                        st.info("Running in Mock Mode: Loading simulated tweets from local dataset...")
                        sample_path = os.path.join(os.path.dirname(__file__), "data", "sample_leads.csv")
                        with open(sample_path, "r", encoding="utf-8") as f:
                            count = import_csv_leads(db, f.read())
                        st.toast(f"Loaded {count} candidate leads (Mock Data)")
                        st.success(f"Discovered and processed {count} candidate leads (Mock Data).")
                        st.rerun()
                    else:
                        x_client = XClient(cfg, db)
                        with st.spinner("Searching X API v2 (safe rate-limited call)..."):
                            posts, users = x_client.search_recent(query_input, max_results=max_results)
                            stats = process_search_results(db, posts, users)
                            st.toast(f"Discovered {stats['discovered']} leads, filtered {stats['filtered']}")
                            st.success(f"Search complete: {stats['discovered']} leads indexed, {stats['filtered']} filtered out.")
                            st.rerun()
                except BudgetExceeded as be:
                    st.error(f"Budget Cap Reached: {be}")
                except Exception as e:
                    st.error(f"Error querying X API: {e}")
                finally:
                    st.session_state.is_processing = False

            st.caption("Notice: Executing live queries deducts directly from your pay-per-use X API budget balance.")

    # Discovered Leads Summary
    st.divider()
    st.markdown("#### Discovered Pipeline Status")
    summary_rows = db.execute("""
        SELECT status, COUNT(*) as count FROM leads GROUP BY status
    """).fetchall()
    
    if summary_rows:
        cols = st.columns(len(summary_rows))
        for i, row in enumerate(summary_rows):
            cols[i].metric(label=f"STATUS: {row['status'].upper()}", value=row["count"])

# ==========================================
# TAB 2: CANDIDATE SCORING
# ==========================================
with tab2:
    leads = db.execute("SELECT * FROM leads ORDER BY score DESC, created_at DESC").fetchall()
    
    if not leads:
        st.info("No leads discovered yet. Please run Discovery or load sample data in Tab 1.")
    else:
        col_act1, col_act2 = st.columns([1.6, 2.4])
        with col_act1:
            if st.button("Score Discovered Leads (Concurrent)", type="primary", disabled=st.session_state.is_processing):
                unscored = db.execute("SELECT user_id FROM leads WHERE status='discovered'").fetchall()
                if not unscored:
                    st.info("All leads are already scored.")
                else:
                    st.session_state.is_processing = True
                    try:
                        progress = st.progress(0)
                        llm = LLMClient(cfg) if cfg.llm_api_key else None
                        uids = [row["user_id"] for row in unscored]
                        
                        with st.spinner(f"Scoring {len(uids)} leads concurrently with ThreadPoolExecutor (5 workers)..."):
                            stats = batch_score_leads(
                                db, uids, llm, max_workers=5,
                                on_progress=lambda done, total: progress.progress(done / total)
                            )
                        st.toast(f"Scored {stats['scored']} leads concurrently")
                        st.success(f"Batch scoring complete: {stats['scored']} scored, {stats['failed']} failed.")
                        st.rerun()
                    finally:
                        st.session_state.is_processing = False

        # Display Leads in Interactive Data Editor
        lead_rows = []
        for l in leads:
            lead_rows.append({
                "User ID": l["user_id"],
                "Username": f"@{l['username']}",
                "Name": l["name"],
                "Location": l["location"],
                "Followers": l["followers"],
                "Score": int(l["score"]) if l["score"] is not None else 0,
                "Fit Reason": l["fit_reason"] or l["filter_reason"] or "",
                "Status": l["status"]
            })
        
        df_leads = pd.DataFrame(lead_rows)
        st.data_editor(
            df_leads,
            hide_index=True,
            use_container_width=True,
            disabled=["User ID", "Username", "Name", "Location", "Followers", "Score", "Fit Reason", "Status"],
            height=340
        )

        # Lead Detail Expander
        st.markdown("#### Candidate Detail & Verified Evidence")
        selected_user = st.selectbox("Select candidate to inspect details", options=[f"@{l['username']} - {l['name']}" for l in leads])
        if selected_user:
            selected_username = selected_user.split(" - ")[0].lstrip("@")
            sel = db.execute("SELECT * FROM leads WHERE username=?", (selected_username,)).fetchone()
            if sel:
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown(f"**Bio:** {sel['bio']}")
                    st.markdown(f"**Location:** {sel['location']}")
                    st.markdown(f"**Profile URL:** [{sel['profile_url']}]({sel['profile_url']})")
                    if sel["score_json"]:
                        score_data = json.loads(sel["score_json"])
                        st.json(score_data)
                with c2:
                    st.markdown("**Raw Tweets / Grounded Evidence:**")
                    evs = json.loads(sel["evidence_json"] or "[]")
                    if evs:
                        for ev in evs:
                            st.info(f"**Tweet ID {ev.get('tweet_id')}:**\n\n\"{ev.get('text')}\"")
                    else:
                        st.caption("No tweet evidence captured.")

# ==========================================
# TAB 3: REVIEW & APPROVALS
# ==========================================
with tab3:
    st.caption("Human-in-the-loop review station: Every message is verified and strictly grounded in real candidate tweet/bio evidence.")

    candidates = db.execute("""
        SELECT l.*, m.id as msg_id, m.draft_text, m.final_text, m.evidence_tweet_id, m.status as msg_status, m.status_detail
        FROM leads l
        LEFT JOIN messages m ON l.user_id = m.user_id
        WHERE l.score >= 50 OR m.id IS NOT NULL
        ORDER BY l.score DESC
    """).fetchall()

    if not candidates:
        st.info("No candidates scored >= 50. Run scoring in Tab 2 first.")
    else:
        for cand in candidates:
            with st.container(border=True):
                col_info, col_draft = st.columns([1, 1])

                with col_info:
                    st.markdown(f"### {cand['name']} (@{cand['username']})")
                    st.markdown(f"**Location:** {cand['location']} | **Rubric Score:** {cand['score']}/100")
                    st.markdown(f"**Fit Assessment:** {cand['fit_reason']}")
                    
                    evs = json.loads(cand["evidence_json"] or "[]")
                    st.markdown("**Evidence Reference:**")
                    if evs:
                        target_ev = next((e for e in evs if str(e.get("tweet_id")) == str(cand["evidence_tweet_id"])), evs[0])
                        st.success(f"**[Verified Tweet {target_ev.get('tweet_id')}]:** {target_ev.get('text')}")
                    else:
                        st.caption("No specific tweet evidence attached.")

                with col_draft:
                    msg_status = cand["msg_status"] or "not_drafted"
                    
                    status_badges = {
                        "drafted": ("DRAFTED", "#F59E0B"),
                        "approved": ("APPROVED", "#2563EB"),
                        "sent": ("SENT", "#10B981"),
                        "blocked": ("BLOCKED", "#DC2626"),
                        "not_drafted": ("NOT DRAFTED", "#6B7280")
                    }
                    badge_text, badge_color = status_badges.get(msg_status, ("UNKNOWN", "#6B7280"))
                    st.markdown(f"**Outreach Status:** <span style='font-size: 0.78rem; font-weight: 700; color: {badge_color}; background-color: #F3F4F6; padding: 2px 8px; border-radius: 4px; border: 1px solid {badge_color}33;'>{badge_text}</span>", unsafe_allow_html=True)

                    current_text = cand["final_text"] or cand["draft_text"] or ""
                    
                    if not current_text:
                        if st.button(f"Generate Grounded Draft (@{cand['username']})", key=f"btn_draft_{cand['user_id']}", disabled=st.session_state.is_processing):
                            st.session_state.is_processing = True
                            try:
                                with st.spinner("Generating grounded draft with self-correction verifier..."):
                                    llm = LLMClient(cfg) if cfg.llm_api_key else None
                                    if llm:
                                        res = generate_draft(db, cand["user_id"], llm)
                                        if res.get("status") == "success":
                                            st.toast(f"Draft generated for @{cand['username']}")
                                            st.success("Draft generated and verified against candidate evidence.")
                                            st.rerun()
                                        else:
                                            st.error(f"Draft generation failed: {res.get('reason')}")
                                    else:
                                        sample_ev = evs[0] if evs else {"tweet_id": "tw_101", "text": "building AI"}
                                        mock_draft = (
                                            f"Hi {cand['name'].split()[0]}, saw your work on {sample_ev['text'][:45]}... "
                                            f"At GenAI Fund, we're building AI ecosystems in Southeast Asia. "
                                            f"How are you approaching scaling and latency on hardware? "
                                            f"No worries at all if you're heads-down."
                                        )
                                        mid = insert_message(db, cand["user_id"], mock_draft, sample_ev["tweet_id"])
                                        with tx(db):
                                            db.execute("UPDATE leads SET status='drafted' WHERE user_id=?", (cand["user_id"],))
                                        st.toast(f"Generated grounded draft for @{cand['username']}")
                                        st.rerun()
                            finally:
                                st.session_state.is_processing = False
                    else:
                        edited_text = st.text_area(
                            "Personalized Message (Editable):",
                            value=current_text,
                            height=120,
                            key=f"text_{cand['user_id']}"
                        )

                        ok, verify_msg = verify_draft({"text": edited_text, "evidence_tweet_id": cand["evidence_tweet_id"] or (evs[0]["tweet_id"] if evs else "none")}, evs)
                        if not ok:
                            st.error(f"Quality Verifier Block: {verify_msg} (Resolve this issue before approving)")

                        btn_col1, btn_col2, btn_col3 = st.columns(3)
                        with btn_col1:
                            approve_disabled = (msg_status == "sent" or not ok or st.session_state.is_processing)
                            if st.button("Approve for Sending", type="primary", key=f"app_{cand['user_id']}", disabled=approve_disabled, help="Requires passing all grounding and anti-cliché verifications"):
                                with tx(db):
                                    db.execute("""
                                        UPDATE messages
                                        SET status='approved', final_text=?, approved_at=CURRENT_TIMESTAMP
                                        WHERE id=?
                                    """, (edited_text, cand["msg_id"]))
                                st.toast(f"Approved message for @{cand['username']}")
                                st.success("Message approved. Ready in Outbox queue.")
                                st.rerun()

                        with btn_col2:
                            if st.button("Regenerate Draft", type="secondary", key=f"regen_{cand['user_id']}", disabled=(msg_status == "sent" or st.session_state.is_processing)):
                                with tx(db):
                                    db.execute("DELETE FROM messages WHERE id=?", (cand["msg_id"],))
                                    db.execute("UPDATE leads SET status='scored' WHERE user_id=?", (cand["user_id"],))
                                st.toast(f"Reset draft for @{cand['username']}")
                                st.rerun()

                        with btn_col3:
                            if st.button("Reject Candidate", type="secondary", key=f"rej_{cand['user_id']}", disabled=(msg_status == "sent" or st.session_state.is_processing)):
                                with tx(db):
                                    db.execute("UPDATE messages SET status='rejected' WHERE id=?", (cand["msg_id"],))
                                st.toast(f"Rejected draft for @{cand['username']}")
                                st.rerun()

# ==========================================
# TAB 4: OUTBOX & TRACKING
# ==========================================
with tab4:
    col_out, col_in = st.columns([1, 1])

    # Outbox
    with col_out:
        st.markdown("### Outbox Dispatch Queue")
        approved_msgs = db.execute("""
            SELECT m.id as msg_id, m.final_text, m.draft_text, l.username, l.name, l.user_id
            FROM messages m
            JOIN leads l ON m.user_id = l.user_id
            WHERE m.status = 'approved'
        """).fetchall()

        if daily_cap_reached:
            st.error(f"Daily send cap reached ({daily_sent}/{cfg.daily_send_cap} DMs sent today). Outbound dispatch is safely paused until tomorrow.")
        elif budget_exhausted:
            st.error(f"Spend ceiling reached (${total_spend:.2f} / ${cfg.max_x_spend_usd:.2f}). Outbound dispatch paused.")

        if not approved_msgs:
            st.info("No approved messages waiting to send.")
        else:
            st.info(f"{len(approved_msgs)} approved message(s) ready in queue.")
            
            send_disabled = (daily_cap_reached or budget_exhausted or st.session_state.is_processing)
            if st.button("Dispatch Next Approved Message", type="primary", disabled=send_disabled):
                st.session_state.is_processing = True
                try:
                    target = approved_msgs[0]
                    mid = target["msg_id"]
                    
                    with st.spinner(f"Claiming and dispatching DM to @{target['username']}..."):
                        if mock_mode or not cfg.x_api_key:
                            class MockX:
                                def send_dm(self, uid, text): return f"mock_evt_{int(time.time())}"
                            res = send_message(db, MockX(), cfg, mid)
                        else:
                            try:
                                x_client = XClient(cfg, db)
                                res = send_message(db, x_client, cfg, mid)
                            except Exception as e:
                                res = type("Res", (), {"status": "failed", "reason": str(e), "is_success": False})()

                    if res.is_success:
                        st.toast(f"Message sent to @{target['username']}")
                        st.success(f"Message delivered to @{target['username']} (Event ID: {res.event_id})")
                    elif res.status == "blocked":
                        st.toast(f"Blocked: {res.reason}")
                        st.error(f"Message Blocked: {res.reason}")
                    else:
                        st.toast(f"Status: {res.status}")
                        st.warning(f"Status: {res.status} ({res.reason})")
                    st.rerun()
                finally:
                    st.session_state.is_processing = False

        # Dispatch History
        st.markdown("#### Message Dispatch History")
        history = db.execute("""
            SELECT m.id, l.username, m.status, m.status_detail, m.sent_at
            FROM messages m
            JOIN leads l ON m.user_id = l.user_id
            WHERE m.status IN ('sent', 'blocked', 'failed')
            ORDER BY m.sent_at DESC, m.id DESC LIMIT 10
        """).fetchall()
        
        if history:
            h_data = [{
                "Username": f"@{h['username']}",
                "Status": h["status"].upper(),
                "Detail": h["status_detail"] or "Delivered",
                "Sent At": h["sent_at"] or "N/A"
            } for h in history]
            st.dataframe(h_data, use_container_width=True)

    # Inbox & Replies
    with col_in:
        st.markdown("### Incoming Replies & Unified Inbox")
        
        btn_refresh, btn_sim = st.columns([1, 1])
        with btn_refresh:
            if st.button("Sync Replies from X API", type="secondary", disabled=st.session_state.is_processing):
                st.session_state.is_processing = True
                try:
                    if mock_mode or not cfg.x_api_key:
                        st.info("Mock Mode: No external API events.")
                    else:
                        x_client = XClient(cfg, db)
                        with st.spinner("Polling recent DM events (cost-optimized checkpoint scan)..."):
                            stats = refresh_replies(db, x_client, max_results=15)
                        st.toast(f"Recorded {stats['new_replies']} new replies")
                        st.success(f"Scanned {stats['total_events_scanned']} events, recorded {stats['new_replies']} new replies.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to fetch replies: {e}")
                finally:
                    st.session_state.is_processing = False

        with btn_sim:
            if st.button("Simulate Inbound Reply (Test)", type="secondary", disabled=st.session_state.is_processing):
                sent_lead = db.execute("""
                    SELECT m.user_id, l.username FROM messages m
                    JOIN leads l ON m.user_id = l.user_id
                    WHERE m.status='sent' LIMIT 1
                """).fetchone()
                if sent_lead:
                    evt_id = f"sim_reply_{int(time.time())}"
                    with tx(db):
                        db.execute("""
                            INSERT OR IGNORE INTO replies (event_id, user_id, text, created_at, handled)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)
                        """, (evt_id, sent_lead["user_id"], "Hey! Thanks for reaching out. Yes, we just open-sourced the kernel and would love to chat with GenAI Fund about deployment in SEA."))
                    st.toast(f"Simulated reply from @{sent_lead['username']}")
                    st.success(f"Simulated reply received from @{sent_lead['username']}")
                    st.rerun()
                else:
                    st.info("Send at least one message first to simulate an incoming reply.")

        # Show Inbox items
        inbox_items = get_inbox_items(db)
        if not inbox_items:
            st.caption("No incoming replies recorded yet.")
        else:
            for item in inbox_items:
                with st.container(border=True):
                    st.markdown(f"**From:** @{item['username']} ({item['name']})")
                    st.caption(f"**Received:** {item['reply_time']}")
                    st.markdown(f"**Candidate Response:**\n> *\"{item['reply_text']}\"*")
                    
                    with st.expander("Outbound message context"):
                        st.caption(item["final_text"])

                    if not item["handled"]:
                        if st.button("Mark Handled", key=f"hnd_{item['event_id']}", disabled=st.session_state.is_processing):
                            mark_reply_handled(db, item["event_id"])
                            st.toast("Marked as handled")
                            st.rerun()
                    else:
                        st.caption("Status: Handled")
