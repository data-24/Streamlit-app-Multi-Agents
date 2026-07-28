"""
============================================================================
 Cortex Multi Agent Studio — app, EXPLAINED line by line (for teaching)
============================================================================
 Same code as appresponse.py, with a comment on almost every line.

 ONE BIG IDEA: Streamlit runs this whole file top-to-bottom every time the
 user clicks or types. To remember things between runs, we use st.session_state.

 WHAT THIS FILE DOES:
   1. draws the page (sidebar + chat)
   2. ask_agent()  -> calls Snowflake, reads the streamed reply, sorts it into
                      answer / thinking / sql / table, and KEEPS the full raw stream
   3. after each answer, silently saves ONE audit row to Snowflake
      (using summarize_audit + save_audit_summary from audit_extractor.py)
============================================================================
"""

import json                       # to read the agent's reply (arrives as JSON text)
import streamlit as st            # the toolkit that turns this script into a web app
# import the two AUDIT helpers from the other file (audit_extractor.py):
#   summarize_audit    -> turn the whole reply into ONE row of facts
#   save_audit_summary -> write that one row into the Snowflake audit table
from audit_extractor import summarize_audit, save_audit_summary

# name the browser tab, its icon, and use the full page width (must be first st command)
st.set_page_config(page_title="Cortex Multi Agent Studio", page_icon="❄️", layout="wide")


# =========================================================================== #
# THE AGENT "MENU" — a dictionary of everything unique about each agent.
# =========================================================================== #
AGENTS = {
    "Healthcare": {                                    # the name shown in the picker
        "display": "Healthcare Agent",                 # friendly name for the banner
        "emoji": "🏥",                                  # banner icon
        "db": "HEALTHCARE_DB",                         # Snowflake database the agent lives in
        "schema": "GOLD",                              # schema inside that database
        "name": "HEALTHCARE_AGENT",                    # the agent's object name in Snowflake
        "tagline": "Ask me about patients, insurance claims, and coverage.",
        "grad": "linear-gradient(135deg, #0e7c86 0%, #14b8a6 100%)",   # banner colour
        "examples": [                                  # starter questions -> buttons
            "How many insurance claims do we have by status?",
            "Which claim status is the most common?",
            "How many claims were submitted in total?",
            "How have claims changed year over year?",
            "What percentage of claims are approved?",
            "How have claims changed year over year?",
            "What percentage of claims are approved?"
        ],
    },
    "Finance": {                                       # a second agent (same shape)
        "display": "Finance Agent", "emoji": "💰",
        "db": "SALES_DB", "schema": "ANALYTICS", "name": "FINANCE_AGENT",
        "tagline": "Ask me about orders, revenue, and sales performance.",
        "grad": "linear-gradient(135deg, #4338ca 0%, #6366f1 100%)",
        "examples": [
            "What is the total revenue by region?",
            "How many orders do we have by status?",
            "Which region has the highest sales?"

        ],
    },
}

# a block of CSS (web styling) — purely cosmetic (banner shape, fonts, badge)
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
    unsafe_allow_html=True,                            # "trust this HTML" (needed for <style>)
)


# =========================================================================== #
# THE SIDEBAR — the controls. Each widget returns the user's choice.
# =========================================================================== #
with st.sidebar:
    st.markdown("### ❄️ Cortex Multi Agent Studio")    # sidebar title
    st.caption("Pick who you want to talk to, then ask a question.")

    st.markdown("#### 🎭 Your role")
    role = st.selectbox("Run as role", ["READER_ROLE", "ACCOUNTADMIN"],   # dropdown -> `role`
                        label_visibility="collapsed")

    st.markdown("#### 🤖 Choose an agent")
    agent_choice = st.radio("Agent", list(AGENTS.keys()),                 # radio -> `agent_choice`
                            label_visibility="collapsed")

    with st.expander("⚙️ Connection settings"):        # hide technical fields in a drawer
        account = st.text_input("Account", value="HTTJFFR-BW29102")       # Snowflake account id
        user = st.text_input("User", value="ADMIN")                       # Snowflake username
        pat_token = st.text_input("Access token (PAT)", type="password",  # the token (login)
                                  help="Role-scoped token. Kept in memory only.")
        show_numbers = st.checkbox("Show the data table under answers", value=True)   # 📊 toggle
        show_thinking = st.checkbox("Show the agent's thinking steps", value=False,    # 🧠 toggle
                                    help="The agent's planning trace (Planning, "
                                         "Reviewing, and the queries it ran).")
        show_sql = st.checkbox("Show the SQL the agent wrote", value=False)            # 🧩 toggle
        show_debug = st.checkbox("🔬 Debug: show raw stream", value=False)             # 🔬 toggle
        # NOTE: there is NO "save audit" checkbox — saving happens automatically & silently.

    if st.button("🗑️ Clear conversation"):             # button returns True when clicked
        st.session_state.messages = []                 # empty the saved chat

agent = AGENTS[agent_choice]                           # look up the chosen agent's details
BASE_URL = f"https://{account}.snowflakecomputing.com" # base web address of the account


# =========================================================================== #
# ask_agent() — CALL SNOWFLAKE, SORT THE REPLY, AND KEEP THE FULL RAW STREAM.
# =========================================================================== #
def ask_agent(question: str) -> dict:
    import requests                                    # web-call library (lazy import)

    url = (f"{BASE_URL}/api/v2/databases/{agent['db']}"          # the agent's ":run" address
           f"/schemas/{agent['schema']}/agents/{agent['name']}:run")
    headers = {
        "Authorization": f"Bearer {pat_token}",        # our token = the ID badge (login)
        "Content-Type": "application/json",            # we send JSON
        "Accept": "text/event-stream",                 # we want the reply as a live stream
    }
    body = {"messages": [{"role": "user",              # the order slip: the user's question
                          "content": [{"type": "text", "text": question}]}]}

    resp = requests.post(url, headers=headers, json=body, stream=True, timeout=120)  # SEND IT
    if resp.status_code != 200:                        # not "200 OK" -> stop, return an error
        return {"text": f"⚠️ Sorry, I couldn't reach the agent (error {resp.status_code}).",
                "thinking_steps": [], "sql_queries": [], "table": None, "debug": ""}

    # ---- empty buckets to fill as the stream arrives ----
    current_event = None            # the LABEL of the piece we're reading now
    answer_parts, final_full = [], ""   # answer fragments, + a fallback full answer
    steps = []                      # readable thinking trace
    sql_queries = []                # SQL the agent ran
    table = None                    # the data for the table
    debug_lines = []                # trimmed copy for the debug panel
    raw_all = []                    # <-- FULL untruncated stream (needed for the AUDIT)

    for raw in resp.iter_lines():                      # read the reply one line at a time
        if raw is None:                                # skip empty keep-alive lines
            continue
        line = raw.decode("utf-8")                     # bytes -> readable text
        if line.strip():                               # if the line isn't blank...
            raw_all.append(line)                       # ...keep the FULL line for the audit
            if len(debug_lines) < 200:
                debug_lines.append(line[:400])         # ...and a trimmed copy for the debug panel

        if line.startswith("event:"):                  # a LABEL line -> remember it
            current_event = line[len("event:"):].strip().lower()
            continue
        if not line.startswith("data:"):               # not a content line -> skip
            continue
        payload = line[len("data:"):].strip()          # the JSON text after "data:"
        if payload in ("[DONE]", ""):                  # end marker / blank -> skip
            continue
        try:
            obj = json.loads(payload)                  # JSON text -> a Python dict
        except json.JSONDecodeError:
            continue

        ev = current_event or ""                       # the label we remembered

        # ----- BUCKET: THE ANSWER (word by word) -----
        if ev == "response.text.delta":
            t = obj.get("text")
            if isinstance(t, str):
                answer_parts.append(t)                 # add the fragment to the answer
            continue
        if ev == "response.text":                      # a full answer block (fallback)
            t = obj.get("text")
            if isinstance(t, str):
                final_full = t
            continue

        # ----- BUCKET: THINKING STEPS (readable planning messages) -----
        if ev == "response.status":
            msg = obj.get("message")
            if isinstance(msg, str) and msg and (not steps or steps[-1] != msg):
                steps.append(msg)                      # add it (skip a repeat of the last)
            continue

        # ----- BUCKET: a TOOL CALL -> a step + the SQL -----
        if ev == "response.tool_use":
            desc = _describe_tool(obj)                 # make a friendly step line
            if desc and (not steps or steps[-1] != desc):
                steps.append(desc)
            sql = (obj.get("input") or {}).get("sql")  # dig out the SQL (safely)
            if isinstance(sql, str) and sql.strip():
                clean = sql.strip().rstrip(";")
                if clean not in sql_queries:           # keep each unique query
                    sql_queries.append(clean)
            continue

        # ----- BUCKET: a TOOL RESULT -> the data for the table -----
        if ev == "response.tool_result":
            tbl = _extract_table(obj)
            if tbl:
                table = tbl                            # keep the last real table
            continue

        # response.thinking (encrypted) is ignored on purpose.

    answer = "".join(answer_parts).strip() or final_full.strip()   # glue the answer
    return {"text": answer or "_(I didn't get a text answer back — please rephrase.)_",
            "thinking_steps": steps, "sql_queries": sql_queries,
            "table": table, "debug": "\n".join(debug_lines),
            "raw_full": "\n".join(raw_all)}            # <-- FULL raw stream for the audit


def _describe_tool(obj) -> str:
    """Turn a tool_use event into a friendly one-line step."""
    inp = obj.get("input") or {}                       # the tool's input (or empty dict)
    sql = inp.get("sql")                               # did it run SQL?
    if isinstance(sql, str) and sql.strip():
        one = " ".join(sql.split())                    # squash SQL onto one line
        if len(one) > 160:                             # trim if very long
            one = one[:160] + " …"
        return "🗄️ Ran a query — " + one
    pq = inp.get("pruning_question")                   # or a data-model lookup?
    if isinstance(pq, str) and pq.strip():
        return "🔎 Looked up the data model for: " + pq
    name = obj.get("name") or "a tool"                 # otherwise just name the tool
    return "🔧 Used " + name


def _extract_table(obj):
    """Pull columns + rows out of a tool_result's result_set (if it has data)."""
    content = obj.get("content")
    if not isinstance(content, list):
        return None
    for item in content:                               # look for the result set
        j = item.get("json") if isinstance(item, dict) else None
        rs = j.get("result_set") if isinstance(j, dict) else None
        if not isinstance(rs, dict):
            continue
        meta = rs.get("resultSetMetaData") or {}
        cols = [c.get("name") for c in (meta.get("rowType") or []) if isinstance(c, dict)]  # columns
        data = rs.get("data")                          # rows
        if cols and isinstance(data, list) and data:
            rows = [[_num(v) for v in r] for r in data]   # convert number-strings -> numbers
            return {"columns": cols, "rows": rows}
    return None


def _num(v):
    """Turn '34880' into 34880 so the table can sort/plot it."""
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


def _render_steps(steps):                              # draw the thinking as numbered steps
    for i, s in enumerate(steps, 1):
        st.markdown(f"✅ **Step {i}** — {s}")


def _render_sql(queries):                              # draw the SQL, highlighted
    for i, q in enumerate(queries, 1):
        if len(queries) > 1:
            st.caption(f"Query {i}")
        st.code(q, language="sql")


def render_table(table):                               # draw the data as a table + chart
    import pandas as pd
    df = pd.DataFrame(table["rows"], columns=table["columns"])
    if df.empty:
        return
    pretty = {c: c.replace("_", " ").title() for c in df.columns}   # friendly column names
    with st.expander("📊 See the numbers", expanded=True):
        st.dataframe(df.rename(columns=pretty), use_container_width=True, hide_index=True)
        label_col = next((c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])), None)
        value_col = next((c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])), None)
        if label_col and value_col and len(df) <= 25:
            try:
                st.bar_chart(df.set_index(label_col)[value_col])
            except Exception:
                pass


# =========================================================================== #
# THE PAGE BODY — banner, example buttons, chat, and the SILENT AUDIT SAVE.
# =========================================================================== #

# the coloured banner (changes with the chosen agent)
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

if "messages" not in st.session_state:                 # the app's MEMORY (holds the chat)
    st.session_state.messages = []

st.markdown('<div class="hint">💡 Try asking:</div>', unsafe_allow_html=True)
cols = st.columns(len(agent["examples"]))              # one column per example button
clicked_example = None
for i, q in enumerate(agent["examples"]):
    if cols[i].button(q, key=f"ex_{agent_choice}_{i}", use_container_width=True):
        clicked_example = q                            # remember a clicked example

st.divider()

# ---- redraw the whole conversation so far (checkboxes decide what shows) ----
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

typed = st.chat_input(f"Ask the {agent['display']} anything…")   # the chat input box
question = typed or clicked_example                    # typed text OR a clicked example

if question:                                           # if there's a new question...
    st.session_state.messages.append({"role": "user", "content": question})   # save it
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        # this answer's buckets (raw_full is the FULL stream we'll audit)
        steps, sql_queries, table, debug, raw_full = [], [], None, "", ""
        if not pat_token:                              # no token -> ask for one
            answer = ("⚠️ Please add your access token under **⚙️ Connection "
                      "settings** in the sidebar first.")
        else:
            with st.spinner(f"{agent['display']} is thinking…"):
                try:
                    result = ask_agent(question)       # CALL Snowflake
                    answer = result["text"]            # the answer
                    steps = result.get("thinking_steps", [])
                    sql_queries = result.get("sql_queries", [])
                    table = result.get("table")
                    debug = result.get("debug", "")
                    raw_full = result.get("raw_full", "")   # <-- keep the full stream
                except Exception as e:  # noqa: BLE001
                    answer = f"⚠️ Something went wrong: {e}"
        st.markdown(answer)                            # show the answer
        if show_thinking and steps:                    # optional 🧠 panel
            with st.expander("🧠 Thinking steps", expanded=True):
                _render_steps(steps)
        if show_sql and sql_queries:                   # optional 🧩 panel
            with st.expander("🧩 SQL the agent used", expanded=True):
                _render_sql(sql_queries)
        if show_numbers and table:                     # optional 📊 panel
            render_table(table)
        if show_debug and debug:                       # optional 🔬 panel
            with st.expander("🔬 Raw stream (debug)", expanded=False):
                st.code(debug)

        # ======================================================= #
        # THE AUDIT SAVE — silent, automatic, ONE row per question
        # ======================================================= #
        if pat_token and raw_full:                     # only if we have a token and a reply
            try:
                summary = summarize_audit(raw_full)    # turn the FULL stream into one row of facts
                save_audit_summary(summary, question, agent_choice, role,   # write it to Snowflake
                                   account, user, pat_token, raw_response=raw_full)
            except Exception:  # noqa: BLE001
                pass                                   # stay invisible; just skip on any error

    # save the answer (+ its panels) into memory so history can redraw it next run
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