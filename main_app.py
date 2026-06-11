import streamlit as st
import os

import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load variables from your .env file
load_dotenv()
# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
ADK_BASE_URL = "http://localhost:8000"
APP_NAME     = "stadium_operations_agent"
USER_ID      = "hackathon_judge"
SESSION_ID   = "biterush_stadium_session"

ES_BASE_URL  = os.getenv("ELASTIC_BASE_URL")   # ← set your Elastic REST base URL
ES_API_KEY   = os.getenv("ELASTIC_API_KEY")     # ← set your API key
ES_INDEX     = "logistics-clusters"

# ─────────────────────────────────────────────
# PAGE CONFIG & GLOBAL CSS
# ─────────────────────────────────────────────
st.set_page_config(page_title="BiteRush Logistics OS", layout="wide", page_icon="🏟️")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    [data-testitem="stSidebar"] hr { border-color: #334155; }

    .br-card {
        background: #ffffff;
        border-radius: 14px;
        padding: 20px 22px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.07);
        border-left: 5px solid #3b82f6;
        margin-bottom: 18px;
        transition: box-shadow 0.2s ease;
    }
    .br-card:hover { box-shadow: 0 8px 28px rgba(0,0,0,0.12); }
    .br-card.batched   { border-left-color: #f59e0b; background: #fffbeb; }
    .br-card.completed { border-left-color: #22c55e; background: #f0fdf4; opacity: 0.75; }

    .card-title { font-weight: 800; font-size: 1.1rem; color: #0f172a; margin-bottom: 6px; }

    .badge {
        display: inline-block;
        padding: 2px 10px; border-radius: 99px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
    }
    .badge-pending   { background:#dbeafe; color:#1d4ed8; }
    .badge-batched   { background:#fef3c7; color:#b45309; }
    .badge-completed { background:#dcfce7; color:#15803d; }

    .metric-tile {
        background: #1e293b; border-radius: 12px;
        padding: 18px 22px; color: white; text-align: center;
    }
    .metric-val   { font-size: 2rem; font-weight: 800; line-height: 1; }
    .metric-label { font-size: 0.76rem; color: #94a3b8; margin-top: 4px;
                    text-transform: uppercase; letter-spacing: 0.06em; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def seconds_between(iso_start: str, iso_end: str) -> int:
    try:
        a = datetime.fromisoformat(iso_start)
        b = datetime.fromisoformat(iso_end)
        return max(0, int((b - a).total_seconds()))
    except Exception:
        return 0

def fmt_duration(seconds: int) -> str:
    if seconds == 0:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


# ─────────────────────────────────────────────
# ELASTICSEARCH WRITER
# ─────────────────────────────────────────────

def post_batches_to_es(batches: list) -> tuple[int, list[str]]:
    """
    Takes the parsed batch list and indexes each one into Elasticsearch.
    Returns (success_count, list_of_error_messages).
    """
    headers = {
        "Authorization": f"ApiKey {ES_API_KEY}",
        "Content-Type":  "application/json",
    }
    success = 0
    errors  = []

    for i, batch in enumerate(batches, start=1):
        cluster_id = f"CLU-{str(i).zfill(3)}"

        # Parse numeric ETA out of the prep_time string e.g. "2m 30s" → 2
        import re
        eta_match = re.search(r'(\d+)\s*m', batch.get("prep_time", ""))
        eta_min   = int(eta_match.group(1)) if eta_match else 0

        doc = {
            "cluster_id":    cluster_id,
            "order_ids":     batch.get("order_ids", []),
            "items":         batch.get("items", []),
            "vendor_id":     "V010",
            "route_steps":   batch.get("route", ""),
            "total_eta_min": eta_min,
            "status":        "PENDING",
            "created_at":    batch.get("created_at", now_iso()),
        }

        # print(doc)
        print(ES_BASE_URL)
        url = f"{ES_BASE_URL}/{ES_INDEX}/_doc/{cluster_id}"
        try:
            r = requests.put(url, json=doc, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                print("entered")
                success += 1
            else:
                print(f"DEBUG: ES Request Failed!")
                print(f"Status: {r.status_code}")
                print(f"Response Body: {r.text}")
                errors.append(f"{cluster_id}: HTTP {r.status_code} — {r.text[:120]}")
        except Exception as e:
            errors.append(f"{cluster_id}: {str(e)}")

    return success, errors


# ─────────────────────────────────────────────
# ADK API CALLS
# ─────────────────────────────────────────────

def create_session() -> bool:
    try:
        r = requests.post(
            f"{ADK_BASE_URL}/apps/{APP_NAME}/users/{USER_ID}/sessions/{SESSION_ID}",
            json={}, timeout=10
        )
        return r.status_code in (200, 409)
    except Exception as e:
        st.error(f"Session error: {e}")
        return False

def trigger_batching_agent() -> bool:
    try:
        if not create_session():
            return False
        r = requests.post(f"{ADK_BASE_URL}/run", json={
            "appName":    APP_NAME,
            "userId":     USER_ID,
            "sessionId":  SESSION_ID,
            "newMessage": {
                "role": "user",
                "parts": [{"text": "group pending order for V010"}]
            },
            "streaming": False
        }, timeout=60)
        if r.status_code != 200:
            st.error(f"Agent error {r.status_code}: {r.text}")
            return False
        return True
    except Exception as e:
        st.error(f"Connection error: {e}")
        return False

def fetch_raw_agent_text() -> str:
    try:
        r = requests.get(
            f"{ADK_BASE_URL}/apps/{APP_NAME}/users/{USER_ID}/sessions/{SESSION_ID}",
            timeout=10
        )
        if r.status_code == 200:
            events = r.json().get("events", [])
            for event in reversed(events):
                if event.get("author") == APP_NAME:
                    parts = event.get("content", {}).get("parts", [{}])
                    text  = parts[0].get("text", "") if parts else ""
                    if text:
                        return text
    except Exception as e:
        st.error(f"Fetch error: {e}")
    return ""


# ─────────────────────────────────────────────
# PARSER
# ─────────────────────────────────────────────

def parse_agent_response(text: str) -> list:
    batches = []
    for section in text.split("---BATCH_START---"):
        if "---BATCH_END---" not in section:
            continue
        content = section.split("---BATCH_END---")[0].strip()
        batch = {
            "batch_title":   "Delivery Batch",
            "order_ids":     [],
            "items":         [],
            "seats":         "N/A",
            "prep_time":     "N/A",
            "route":         "N/A",
            "status":        "PENDING",
            "created_at":    now_iso(),
            "dispatched_at": None,
            "completed_at":  None,
        }
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("Group:"):
                batch["batch_title"] = line.replace("Group:", "").strip().strip("[]")
            elif line.startswith("Orders:"):
                raw = line.replace("Orders:", "").strip().strip("[]")
                batch["order_ids"] = [o.strip() for o in raw.split(",") if o.strip()]
            elif line.startswith("Seats:"):
                batch["seats"] = line.replace("Seats:", "").strip().strip("[]")
            elif line.startswith("Food:"):
                raw = line.replace("Food:", "").strip().strip("[]")
                batch["items"] = [f.strip() for f in raw.split(",") if f.strip()]
            elif line.startswith("Max_Wait:"):
                batch["prep_time"] = line.replace("Max_Wait:", "").strip().strip("[]")
            elif line.startswith("Route:"):
                batch["route"] = line.replace("Route:", "").strip().strip("[]")
        batches.append(batch)
    return batches


# ─────────────────────────────────────────────
# STATE MACHINE TRANSITIONS
# ─────────────────────────────────────────────

def dispatch_batch(idx: int):
    st.session_state.batches[idx]["status"]        = "BATCHED"
    st.session_state.batches[idx]["dispatched_at"] = now_iso()

def complete_batch(idx: int):
    st.session_state.batches[idx]["status"]       = "COMPLETED"
    st.session_state.batches[idx]["completed_at"] = now_iso()


# ─────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────

def calc_metrics(batches: list) -> dict:
    pending   = [b for b in batches if b["status"] == "PENDING"]
    batched   = [b for b in batches if b["status"] == "BATCHED"]
    completed = [b for b in batches if b["status"] == "COMPLETED"]

    dispatch_times = []
    for b in completed + batched:
        if b.get("dispatched_at") and b.get("created_at"):
            dispatch_times.append(seconds_between(b["created_at"], b["dispatched_at"]))

    completion_times = []
    for b in completed:
        if b.get("dispatched_at") and b.get("completed_at"):
            completion_times.append(seconds_between(b["dispatched_at"], b["completed_at"]))

    avg_d = int(sum(dispatch_times)   / len(dispatch_times))   if dispatch_times   else 0
    avg_c = int(sum(completion_times) / len(completion_times)) if completion_times else 0

    return {
        "pending":        len(pending),
        "batched":        len(batched),
        "completed":      len(completed),
        "avg_dispatch":   fmt_duration(avg_d),
        "avg_completion": fmt_duration(avg_c),
    }


# ─────────────────────────────────────────────
# CARD RENDERER
# ─────────────────────────────────────────────

def render_batch_card(idx: int, data: dict, tab_id: str = ""):
    status     = data["status"]
    css_class  = {"PENDING": "", "BATCHED": "batched", "COMPLETED": "completed"}.get(status, "")
    badge_cls  = {"PENDING": "badge-pending", "BATCHED": "badge-batched",
                  "COMPLETED": "badge-completed"}.get(status, "")
    # Unique prefix per tab so the same card rendered in multiple tabs never collides
    k = f"{tab_id}_{idx}"

    ts_parts = []
    if data.get("dispatched_at"):
        ts_parts.append(f"🚀 Dispatched {data['dispatched_at'][11:19]} UTC")
    if data.get("completed_at") and data.get("dispatched_at"):
        dur = fmt_duration(seconds_between(data["dispatched_at"], data["completed_at"]))
        ts_parts.append(f"✅ Delivered in {dur}")
    ts_line = " &nbsp;·&nbsp; ".join(ts_parts)

    st.markdown(f"""
        <div class="br-card {css_class}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div class="card-title">📦 {data.get('batch_title','Batch')}</div>
                <span class="badge {badge_cls}">{status}</span>
            </div>
            <div style="color:#ef4444;font-weight:700;margin-top:8px;">
                ⏱️ Max Wait: {data.get('prep_time','N/A')}
            </div>
            <div style="font-size:0.88rem;margin-top:4px;color:#475569;">
                💺 {data.get('seats','N/A')}
            </div>
            <hr style="margin:10px 0;border-color:#e2e8f0;">
            <div style="font-size:0.82rem;">
                <strong>🍔 Food:</strong> {", ".join(data.get('items',[])) or "—"}
            </div>
            <div style="font-size:0.82rem;margin-top:3px;">
                <strong>📋 Orders:</strong> {", ".join(data.get('order_ids',[])) or "—"}
            </div>
            <div style="font-size:0.82rem;margin-top:3px;color:#475569;">
                <strong>🗺️ Route:</strong> {data.get('route','N/A')}
            </div>
            {"<div style='font-size:0.75rem;color:#64748b;margin-top:8px;'>" + ts_line + "</div>" if ts_line else ""}
        </div>
    """, unsafe_allow_html=True)

    if status == "PENDING":
        if st.button("🚀 Dispatch Batch", key=f"dispatch_{k}", type="primary"):
            dispatch_batch(idx)
            st.rerun()
    elif status == "BATCHED":
        col_a, col_b = st.columns([3, 2])
        with col_a:
            st.button("⏳ Dispatching…", key=f"dispatching_{k}", disabled=True)
        with col_b:
            if st.button("✅ Mark Complete", key=f"complete_{k}"):
                complete_batch(idx)
                st.rerun()
    elif status == "COMPLETED":
        st.button("☑️ Delivered", key=f"done_{k}", disabled=True)


# ─────────────────────────────────────────────
# SESSION INIT
# ─────────────────────────────────────────────

if "agent_run_complete" not in st.session_state:
    st.session_state.agent_run_complete = False
if "batches" not in st.session_state:
    st.session_state.batches = []
if "es_sync_status" not in st.session_state:
    st.session_state.es_sync_status = None   # None | "ok" | "partial" | "error"


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ BiteRush OS")
    st.markdown("---")
    menu_selection = st.radio(
        "nav", ["Dashboard", "Analytics", "Profile", "Settings"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.subheader("🤖 AI Command Console")
    if st.button("🔄 Sync Logistics Data"):
        st.session_state.agent_run_complete = False
        st.session_state.batches = []
        st.session_state.es_sync_status = None
        st.rerun()

    if st.session_state.batches:
        m = calc_metrics(st.session_state.batches)
        st.markdown("---")
        st.caption("LIVE PIPELINE")
        st.markdown(
            f"🟡 **Pending:** {m['pending']}  \n"
            f"🟠 **En Route:** {m['batched']}  \n"
            f"🟢 **Done:** {m['completed']}"
        )

    # Show ES sync status in sidebar
    if st.session_state.es_sync_status == "ok":
        st.success("✅ Synced to Elasticsearch")
    elif st.session_state.es_sync_status == "partial":
        st.warning("⚠️ Partial ES sync — check logs")
    elif st.session_state.es_sync_status == "error":
        st.error("❌ ES sync failed")


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

if menu_selection == "Dashboard":
    st.title("🏟️ Logistics Dashboard")

    # Auto-trigger agent on first load
    if not st.session_state.agent_run_complete:
        with st.spinner("Connecting to BiteRush AI dispatcher…"):
            if trigger_batching_agent():
                raw     = fetch_raw_agent_text()
                batches = parse_agent_response(raw)
                st.session_state.batches = batches

                # ── POST TO ELASTICSEARCH ──────────────────────────
                if batches:
                    success, errors = post_batches_to_es(batches)
                    if errors:
                        st.session_state.es_sync_status = "partial" if success else "error"
                        for err in errors:
                            st.warning(f"ES write error: {err}")
                    else:
                        st.session_state.es_sync_status = "ok"
                # ───────────────────────────────────────────────────

                st.session_state.agent_run_complete = True
                st.rerun()
            else:
                st.error("Dispatcher offline. Is `adk api_server` running on port 8000?")
                st.stop()

    # ── Metrics row ──
    m  = calc_metrics(st.session_state.batches)
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, (val, label) in zip(
        [c1, c2, c3, c4, c5],
        [
            (m["pending"],        "Pending"),
            (m["batched"],        "En Route"),
            (m["completed"],      "Completed"),
            (m["avg_dispatch"],   "Avg Dispatch Time"),
            (m["avg_completion"], "Avg Delivery Time"),
        ]
    ):
        with col:
            st.markdown(f"""
                <div class="metric-tile">
                    <div class="metric-val">{val}</div>
                    <div class="metric-label">{label}</div>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Filter tabs ──
    tab_pending, tab_en_route, tab_completed, tab_all = st.tabs(
        ["🟡 Pending", "🟠 En Route", "🟢 Completed", "📋 All"]
    )

    def render_filtered(filter_status, tab_id: str):
        filtered = [
            (i, b) for i, b in enumerate(st.session_state.batches)
            if filter_status is None or b["status"] == filter_status
        ]
        if not filtered:
            st.info("No batches in this state.")
            return
        cols = st.columns(3)
        for pos, (real_idx, data) in enumerate(filtered):
            with cols[pos % 3]:
                render_batch_card(real_idx, data, tab_id=tab_id)

    with tab_pending:
        render_filtered("PENDING", "pending")
    with tab_en_route:
        render_filtered("BATCHED", "enroute")
    with tab_completed:
        render_filtered("COMPLETED", "completed")
    with tab_all:
        render_filtered(None, "all")


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────

elif menu_selection == "Analytics":
    st.title("📊 Operational Insights")

    if not st.session_state.batches:
        st.info("No data yet — run the dispatcher from the Dashboard first.")
    else:
        m     = calc_metrics(st.session_state.batches)
        total = len(st.session_state.batches)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Batches",     total)
        c2.metric("Avg Dispatch Time", m["avg_dispatch"],
                  help="Time from batch creation → dispatch click")
        c3.metric("Avg Delivery Time", m["avg_completion"],
                  help="Time from dispatch → runner marks complete")

        st.markdown("---")
        st.subheader("Batch Timeline")
        for b in st.session_state.batches:
            created    = b.get("created_at",    "")[:19].replace("T", " ") + " UTC"
            dispatched = (b.get("dispatched_at","—") or "—")[:19].replace("T", " ")
            completed  = (b.get("completed_at", "—") or "—")[:19].replace("T", " ")
            if dispatched != "—":
                dispatched += " UTC"
            if completed != "—":
                completed += " UTC"

            with st.expander(f"📦 {b['batch_title']}  [{b['status']}]"):
                st.write(f"**Created:**    {created}")
                st.write(f"**Dispatched:** {dispatched}")
                st.write(f"**Completed:**  {completed}")
                st.write(f"**Orders:**     {', '.join(b.get('order_ids', []))}")
                st.write(f"**Food:**       {', '.join(b.get('items', []))}")


# ─────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────

elif menu_selection == "Profile":
    st.title("👤 Vendor Profile")
    with st.container(border=True):
        st.subheader("Franky Vadapav HQ")
        st.write("**Vendor ID:** #BR-9921")
        st.write("**Location:** North Stadium Gate")
        st.write("**Account Status:** ✅ Verified")
        st.button("Edit Profile")


# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────

elif menu_selection == "Settings":
    st.title("⚙️ System Settings")
    st.toggle("Enable Auto-Dispatch")
    st.toggle("Dark Mode", value=True)
    st.markdown("---")
    if st.button("🚪 Sign Out", type="primary"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.warning("Signed out. Refresh to restart.")
        st.stop()