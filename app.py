"""
Cortex Multi Agent Studio — friendly chat app for Snowflake Cortex Agents.
Pick a role, pick an agent, ask in plain English.

This version parses the agent's REAL streaming format:
  • response.status        -> the readable "thinking steps" (Planning, Reviewing, ...)
  • response.tool_use       -> the SQL the agent runs
  • response.tool_result    -> the actual data (used to build the table, no re-run needed)
  • response.text.delta     -> the final answer, arriving word by word

Run:
  python -m streamlit run app.py
"""

import json
import streamlit as st
from audit_extractor import summarize_audit, save_audit_summary

st.set_page_config(page_title="Cortex Multi Agent Studio", page_icon="❄️", layout="wide")

# --------------------------------------------------------------------------- #
# Agent catalogue
# --------------------------------------------------------------------------- #
AGENTS = {
    "Healthcare": {
        "display": "Healthcare Agent", "emoji": "🏥",
        "db": "HEALTHCARE_DB", "schema": "GOLD", "name": "HEALTHCARE_AGENT",
        "tagline": "Ask me about patients, insurance claims, and coverage.",
        "grad": "linear-gradient(135deg, #0e7c86 0%, #14b8a6 100%)",
        "examples": [
            "How many insurance claims do we have by status?",
            "Which claim status is the most common?",
            "How many claims were submitted in total?",
            "which are top 5 departments by number of patient admissions",
            "what is the average treatment cost grouped by outcomes",
            "How have claims changed year over year?",
            "What percentage of claims are approved?",
            "Which insurance provider has the most claims?",
            "What is the total treatment cost by department?",
        ],
    },
    "Finance": {
        "display": "Finance Agent", "emoji": "💰",
        "db": "SALES_DB", "schema": "ANALYTICS", "name": "FINANCE_AGENT",
        "tagline": "Ask me about orders, revenue, and sales performance.",
        "grad": "linear-gradient(135deg, #4338ca 0%, #6366f1 100%)",
        "examples": [
            "What is the total revenue by region?",
            "How many orders do we have by status?",
            "Which region has the highest sales?",
        ],
    },
}

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 900px;}
      .hero {display:flex; align-items:center; gap:22px; padding:28px 32px;
             border-radius:20px; color:#fff; box-shadow:0 8px 24px rgba(16,50,79,.18);
             margin-bottom:8px;}
      .hero-emoji {font-size:56px; line-height:1;}
      .hero-title {font-size:34px; font-weight:800; letter-spacing:-.5px;}
      .hero-sub {font-size:16px; opacity:.92; margin-top:4px;}
      .badge {display:inline-block; margin-top:10px; padding:4px 12px;
              background:rgba(255,255,255,.22); border-radius:999px;
              font-size:13px; font-weight:600;}
      .hint {color:#6b7280; font-size:14px; margin:18px 0 6px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### ❄️ Cortex Multi Agent Studio")
    st.caption("Pick who you want to talk to, then ask a question.")

    # 🎭 The Snowflake role the app connects as (the shared token is restricted to READER_ROLE).
    st.markdown("#### 🎭 Your role")
    role = st.selectbox("Run as role", ["READER_ROLE", "ACCOUNTADMIN"],
                        label_visibility="collapsed")

    # 🤖 Which agent to talk to. THIS defines `agent_choice`, used all over the app —
    # it must stay active (never comment it out).
    st.markdown("#### 🤖 Choose an agent")
    agent_choice = st.radio("Agent", list(AGENTS.keys()), label_visibility="collapsed")

    # 🙋 Who is asking. This is ONLY for the audit table's `user_name` column.
    # The database login stays ADMIN (via the one shared token); this picker just
    # records the real person (Priyanka / Anand) so the audit shows who asked.
    # Add more names to this list as more people use the app.
    st.markdown("#### 🙋 Your name")
    asked_by = st.selectbox("Your name", ["PRIYANKA", "ANAND_JHA"],
                            label_visibility="collapsed",
                            help="Who is asking — saved in the audit table.")

    # ⚙️ Connection (account, login user, shared token) is read from a hidden config file:
    #   .streamlit/secrets.toml   (set up ONCE, git-ignored, never shown in the app)
    # The login user is ADMIN — the owner of the one shared token — but it's plumbing only
    # and is NEVER shown here or recorded. What the audit records is "Your name" above.
    account = st.secrets["snowflake"]["account"]
    user = st.secrets["snowflake"]["user"]        # = ADMIN, hidden — just carries the shared token
    pat_token = st.secrets["snowflake"]["token"]  # the one shared token, hidden

    with st.expander("⚙️ Display options",expanded=True):
        show_numbers = st.checkbox("Show the data table under answers", value=True)
        show_thinking = st.checkbox("Show the agent's thinking steps", value=False,
                                    help="The agent's planning trace (Planning, "
                                         "Reviewing, and the queries it ran).")
        show_sql = st.checkbox("Show the SQL the agent wrote", value=False)
        show_debug = st.checkbox("🔬 Debug: show raw stream", value=False)

    if st.button("🗑️ Clear conversation"):
        st.session_state.messages = []

agent = AGENTS[agent_choice]                                       # needs agent_choice (above)
BASE_URL = f"https://{account}.snowflakecomputing.com"


# --------------------------------------------------------------------------- #
# Agent call — parses the agent's real streaming format
# --------------------------------------------------------------------------- #
def ask_agent(question: str) -> dict:
    import requests
    url = (f"{BASE_URL}/api/v2/databases/{agent['db']}"
           f"/schemas/{agent['schema']}/agents/{agent['name']}:run")
    headers = {
        "Authorization": f"Bearer {pat_token}",                   # the shared token authenticates the agent call
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body = {"messages": [{"role": "user",
                          "content": [{"type": "text", "text": question}]}]}
    resp = requests.post(url, headers=headers, json=body, stream=True, timeout=120)
    if resp.status_code != 200:
        return {"text": f"⚠️ Sorry, I couldn't reach the agent (error {resp.status_code}).",
                "thinking_steps": [], "sql_queries": [], "table": None, "debug": ""}

    current_event = None
    answer_parts, final_full = [], ""
    steps = []              # readable thinking trace (status + tool actions)
    sql_queries = []        # SQL the agent actually ran
    table = None            # data pulled straight from tool_result
    debug_lines = []
    raw_all = []            # FULL untruncated stream (for the audit table)

    for raw in resp.iter_lines():
        if raw is None:
            continue
        line = raw.decode("utf-8")
        if line.strip():
            raw_all.append(line)                    # keep every full line for the audit
            if len(debug_lines) < 200:
                debug_lines.append(line[:400])      # trimmed copy for the debug panel

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip().lower()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue

        ev = current_event or ""

        # ----- THE FINAL ANSWER (arrives word-by-word) -----
        if ev == "response.text.delta":
            t = obj.get("text")
            if isinstance(t, str):
                answer_parts.append(t)
            continue
        if ev == "response.text":                      # a consolidated final block
            t = obj.get("text")
            if isinstance(t, str):
                final_full = t
            continue

        # ----- THINKING STEPS (the readable planning trace) -----
        if ev == "response.status":
            msg = obj.get("message")
            if isinstance(msg, str) and msg and (not steps or steps[-1] != msg):
                steps.append(msg)
            continue

        # ----- A TOOL CALL: describe it as a step + grab its SQL -----
        if ev == "response.tool_use":
            desc = _describe_tool(obj)
            if desc and (not steps or steps[-1] != desc):
                steps.append(desc)
            sql = (obj.get("input") or {}).get("sql")
            if isinstance(sql, str) and sql.strip():
                clean = sql.strip().rstrip(";")
                if clean not in sql_queries:
                    sql_queries.append(clean)
            continue

        # ----- A TOOL RESULT: pull the data for the table (keep the last real one) -----
        if ev == "response.tool_result":
            tbl = _extract_table(obj)
            if tbl:
                table = tbl
            continue

        # response.thinking (encrypted signature) and *.status → ignored.

    answer = "".join(answer_parts).strip() or final_full.strip()
    return {"text": answer or "_(I didn't get a text answer back — please rephrase.)_",
            "thinking_steps": steps, "sql_queries": sql_queries,
            "table": table, "debug": "\n".join(debug_lines),
            "raw_full": "\n".join(raw_all)}


def _describe_tool(obj) -> str:
    """Turn a tool_use event into a friendly one-line step."""
    inp = obj.get("input") or {}
    sql = inp.get("sql")
    if isinstance(sql, str) and sql.strip():
        one = " ".join(sql.split())
        if len(one) > 160:
            one = one[:160] + " …"
        return "🗄️ Ran a query — " + one
    pq = inp.get("pruning_question")
    if isinstance(pq, str) and pq.strip():
        return "🔎 Looked up the data model for: " + pq
    name = obj.get("name") or "a tool"
    return "🔧 Used " + name


def _extract_table(obj):
    """Pull columns + rows out of a tool_result's result_set (if it has data)."""
    content = obj.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        j = item.get("json") if isinstance(item, dict) else None
        rs = j.get("result_set") if isinstance(j, dict) else None
        if not isinstance(rs, dict):
            continue
        meta = rs.get("resultSetMetaData") or {}
        cols = [c.get("name") for c in (meta.get("rowType") or []) if isinstance(c, dict)]
        data = rs.get("data")
        if cols and isinstance(data, list) and data:
            rows = [[_num(v) for v in r] for r in data]
            return {"columns": cols, "rows": rows}
    return None


def _num(v):
    """Turn numeric strings like '34880' or '2108071460.00' into real numbers."""
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return v
        try:
            f = float(s)
            return int(f) if f.is_integer() else f
        except ValueError:
            return v
    return v


def _render_steps(steps):
    for i, s in enumerate(steps, 1):
        st.markdown(f"✅ **Step {i}** — {s}")


def _render_sql(queries):
    for i, q in enumerate(queries, 1):
        if len(queries) > 1:
            st.caption(f"Query {i}")
        st.code(q, language="sql")


def render_table(table):
    import pandas as pd
    df = pd.DataFrame(table["rows"], columns=table["columns"])
    if df.empty:
        return
    pretty = {c: c.replace("_", " ").title() for c in df.columns}
    with st.expander("📊 See the numbers", expanded=True):
        st.dataframe(df.rename(columns=pretty), use_container_width=True, hide_index=True)
        label_col = next((c for c in df.columns
                          if not pd.api.types.is_numeric_dtype(df[c])), None)
        value_col = next((c for c in df.columns
                          if pd.api.types.is_numeric_dtype(df[c])), None)
        if label_col and value_col and len(df) <= 25:
            try:
                st.bar_chart(df.set_index(label_col)[value_col])
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Hero header
# --------------------------------------------------------------------------- #
st.markdown(
    f"""
    <div class="hero" style="background:{agent['grad']}">
      <div class="hero-emoji">{agent['emoji']}</div>
      <div>
        <div class="hero-title">{agent['display']}</div>
        <div class="hero-sub">{agent['tagline']}</div>
        <span class="badge">🎭 Role: {role}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = []

st.markdown('<div class="hint">💡 Try asking:</div>', unsafe_allow_html=True)
clicked_example = None
PER_ROW = 3                                   # how many buttons per row (raise/lower to taste)
examples = agent["examples"]
for start in range(0, len(examples), PER_ROW):        # step through the list 3 at a time
    cols = st.columns(PER_ROW)                        # always 3 columns wide -> uniform button size
    for j, q in enumerate(examples[start:start + PER_ROW]):
        if cols[j].button(q, key=f"ex_{agent_choice}_{start + j}", use_container_width=True):
            clicked_example = q

st.divider()

# --------------------------------------------------------------------------- #
# Chat history
# --------------------------------------------------------------------------- #
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if show_thinking and m.get("thinking_steps"):
            with st.expander("🧠 Thinking steps", expanded=True):
                _render_steps(m["thinking_steps"])
        if show_sql and m.get("sql_queries"):
            with st.expander("🧩 SQL the agent used", expanded=True):
                _render_sql(m["sql_queries"])
        if show_numbers and m.get("table"):
            render_table(m["table"])
        if show_debug and m.get("debug"):
            with st.expander("🔬 Raw stream (debug)", expanded=False):
                st.code(m["debug"])

typed = st.chat_input(f"Ask the {agent['display']} anything…")
question = typed or clicked_example

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        steps, sql_queries, table, debug, raw_full = [], [], None, "", ""
        if not pat_token:
            answer = ("⚠️ Please add your access token under **⚙️ Connection "
                      "settings** in the sidebar first.")
        else:
            with st.spinner(f"{agent['display']} is thinking…"):
                try:
                    result = ask_agent(question)
                    answer = result["text"]
                    steps = result.get("thinking_steps", [])
                    sql_queries = result.get("sql_queries", [])
                    table = result.get("table")
                    debug = result.get("debug", "")
                    raw_full = result.get("raw_full", "")
                except Exception as e:  # noqa: BLE001
                    answer = f"⚠️ Something went wrong: {e}"
        st.markdown(answer)
        if show_thinking and steps:
            with st.expander("🧠 Thinking steps", expanded=True):
                _render_steps(steps)
        if show_sql and sql_queries:
            with st.expander("🧩 SQL the agent used", expanded=True):
                _render_sql(sql_queries)
        if show_numbers and table:
            render_table(table)
        if show_debug and debug:
            with st.expander("🔬 Raw stream (debug)", expanded=False):
                st.code(debug)

        # ---- save ONE audit row per question ----
        # Connection logs in as `user` (ADMIN, the shared-token owner), but we record
        # `user_name=asked_by` (the person picked in the sidebar) into the user_name column,
        # so the audit shows WHO asked even though everyone shares one token.
        if pat_token and raw_full:
            try:
                summary = summarize_audit(raw_full)
                save_audit_summary(summary, question, agent_choice, role,
                                   account, user, pat_token, raw_response=raw_full,
                                   user_name=asked_by)
                st.success("✅ Audit row saved.")
            except Exception as e:  # noqa: BLE001
                st.error(f"⚠️ Audit save failed: {e}")

    msg = {"role": "assistant", "content": answer}
    if steps:
        msg["thinking_steps"] = steps
    if sql_queries:
        msg["sql_queries"] = sql_queries
    if table:
        msg["table"] = table
    if debug:
        msg["debug"] = debug
    st.session_state.messages.append(msg)