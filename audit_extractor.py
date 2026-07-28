"""
============================================================================
 audit_extractor.py — 
============================================================================
 This file's whole job: take the FULL raw response from the agent and
 (1) squash it into ONE summary row per question, and
 (2) write that row into the Snowflake table HEALTHCARE_DB.RAW.AUDIT_RESPONSE.

 The app (appresponse.py) uses just two functions from here:
     summarize_audit(raw_stream)   -> one dict of facts
     save_audit_summary(...)       -> INSERT that dict as one row

 (This is the teaching copy — the real, importable file is audit_extractor.py.)
============================================================================
"""

import json                        # to read each "data:" line (it's JSON text)


# =========================================================================== #
# STEP 1 — build_audit(): read the stream into a list of per-event rows.
# This is the base parser; summarize_audit() is built on top of it.
# =========================================================================== #
def build_audit(raw_stream: str) -> list:
    rows = []                                   # we'll collect one dict per meaningful event
    current_event = None                        # remember the current "event:" label

    for line in raw_stream.splitlines():        # go through the stream one line at a time
        line = line.strip()                     # trim spaces
        if not line:                            # skip blank lines
            continue

        if line.startswith("event:"):           # a LABEL line -> remember it
            current_event = line[len("event:"):].strip().lower()
            continue
        if not line.startswith("data:"):        # not content -> skip
            continue
        payload = line[len("data:"):].strip()   # the JSON text after "data:"
        if payload in ("[DONE]", ""):           # end marker / blank -> skip
            continue
        try:
            obj = json.loads(payload)           # JSON text -> a Python dict
        except json.JSONDecodeError:
            continue

        ev = current_event or ""                # the label we remembered
        seq = obj.get("sequence_number")        # the order number of this event

        # ---- sort this event into an audit row, based on its label ----
        if ev == "response.status":             # a planning/reviewing status
            rows.append(_row(seq, ev, status=obj.get("status"), message=obj.get("message")))

        elif ev == "response.thinking":         # the agent's reasoning (full block)
            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                rows.append(_row(seq, ev, reasoning=txt.strip()))

        elif ev == "response.tool_use":         # the agent ran a tool / SQL
            inp = obj.get("input") or {}
            rows.append(_row(seq, ev,
                             tool_name=obj.get("name"), tool_type=obj.get("type"),
                             tool_use_id=obj.get("tool_use_id"),
                             sql=_one_line(inp.get("sql")),
                             semantic_model=inp.get("semantic_model"),
                             pruning_question=inp.get("pruning_question")))

        elif ev == "response.tool_result.status":   # capture the Snowflake Query ID
            details = obj.get("details") or {}
            if details.get("QueryID"):
                rows.append(_row(seq, ev, status=obj.get("status"),
                                 message=obj.get("message"), query_id=details.get("QueryID")))

        elif ev in ("response.tool_result", "response.table"):   # the query RESULT (rows)
            info = _result_info(obj)            # pull query_id, row count, columns
            if info:
                rows.append(_row(seq, ev, **info))

        elif ev == "response.text":             # the final consolidated answer
            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                rows.append(_row(seq, ev, answer=txt.strip()))

    return rows                                 # a list of per-event dicts


# --------------------------------------------------------------------------- #
# small helpers used by build_audit()
# --------------------------------------------------------------------------- #
# every audit row has these keys (blank if unused) so the shape is consistent
COLUMNS = ["sequence_number", "event", "status", "message", "reasoning",
           "tool_name", "tool_type", "tool_use_id", "sql", "semantic_model",
           "pruning_question", "query_id", "num_rows", "columns", "model"]


def _row(seq, event, **kw):
    """Build one row with every column present (blank if unused), then fill in kw."""
    row = {c: "" for c in COLUMNS}              # start with every column blank
    row["sequence_number"] = seq if seq is not None else ""
    row["event"] = event                        # remember which event this row is
    for k, v in kw.items():                     # fill in whatever was passed
        if v is not None:
            row[k] = v
    return row


def _one_line(sql):
    """Squash a multi-line SQL string onto one clean line (or return '')."""
    if isinstance(sql, str) and sql.strip():
        return " ".join(sql.split())            # split on all whitespace, rejoin with 1 space
    return ""


def _result_info(obj):
    """Pull query_id, row count, and column names out of a tool_result / table event."""
    rs = obj.get("result_set")                  # response.table has result_set at the top
    query_id = obj.get("query_id")
    if rs is None:                              # response.tool_result nests it deeper
        for item in (obj.get("content") or []):
            j = item.get("json") if isinstance(item, dict) else None
            if isinstance(j, dict) and "result_set" in j:
                rs = j.get("result_set")
                query_id = j.get("query_id", query_id)
                break
    if not isinstance(rs, dict):
        return None
    meta = rs.get("resultSetMetaData") or {}
    cols = [c.get("name") for c in (meta.get("rowType") or []) if isinstance(c, dict)]  # names
    return {"query_id": query_id or "",
            "num_rows": meta.get("numRows", ""),
            "columns": ", ".join(cols)}


# =========================================================================== #
# STEP 2 — find the MODEL name (dynamically) from the usage metadata.
# =========================================================================== #
def _find_model(node, found):
    """Recursively search anything for a 'model_name' value and collect it."""
    if isinstance(node, dict):                  # if it's a dictionary...
        for k, v in node.items():
            if k == "model_name" and isinstance(v, str) and v.strip():
                found.add(v.strip())            # found a model name -> keep it
            else:
                _find_model(v, found)           # otherwise dig deeper
    elif isinstance(node, list):                # if it's a list...
        for item in node:
            _find_model(item, found)


def _extract_model(raw_stream: str) -> str:
    """Scan the whole stream and return the model name(s) from the metadata."""
    models = set()                              # a set = no duplicates
    for line in raw_stream.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            _find_model(json.loads(payload), models)   # search this piece for model_name
        except json.JSONDecodeError:
            continue
    return ", ".join(sorted(models))            # join them into one string (usually just one)


# =========================================================================== #
# STEP 3 — summarize_audit(): collapse everything into ONE row per question.
# =========================================================================== #
def summarize_audit(raw_stream: str) -> dict:
    rows = build_audit(raw_stream)              # first get the per-event rows
    final_answer, reasonings, planning = "", [], []
    sqls, query_ids, tools = [], [], []
    num_rows, result_columns = "", ""

    for r in rows:                              # walk the per-event rows and gather facts
        ev = r.get("event", "")
        if ev == "response.text":
            a = r.get("answer", "")
            if a:
                final_answer = a               # the final answer
        elif ev == "response.thinking":
            if r.get("reasoning"):
                reasonings.append(r["reasoning"])          # collect reasoning
        elif ev == "response.status":
            m = r.get("message", "")
            if m and (not planning or planning[-1] != m):
                planning.append(m)             # collect planning messages (no repeats)
        elif ev == "response.tool_use":
            if r.get("sql") and r["sql"] not in sqls:
                sqls.append(r["sql"])          # collect each unique SQL
            if r.get("tool_name") and r["tool_name"] not in tools:
                tools.append(r["tool_name"])   # collect tool names
        elif ev in ("response.tool_result", "response.table"):
            if r.get("query_id") and r["query_id"] not in query_ids:
                query_ids.append(r["query_id"])            # collect query ids
            if r.get("num_rows") not in ("", None):
                num_rows = r["num_rows"]       # rows the query returned
            if r.get("columns"):
                result_columns = r["columns"]  # result column names

    # return ONE dict of facts (this becomes one row in the table)
    return {
        "final_answer": final_answer,
        "reasoning": "\n".join(reasonings),         # join reasoning lines
        "planning_trace": " → ".join(planning),     # "Planning → Choosing → Reviewing …"
        "tools_used": ", ".join(tools),
        "sql_queries": "\n\n".join(sqls),           # all SQL, separated by blank lines
        "query_ids": ", ".join(query_ids),
        "num_rows": num_rows,
        "result_columns": result_columns,
        "model": _extract_model(raw_stream),        # the model, read from the metadata
    }


# =========================================================================== #
# STEP 4 — save_audit_summary(): INSERT that one row into Snowflake.
# =========================================================================== #
def _int_or_none(v):
    """Turn '' or a bad value into None so a NUMBER column accepts it."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def save_audit_summary(summary, question, agent, role, account, user, token, raw_response="",
                       warehouse="HEALTHCARE_WH", database="HEALTHCARE_DB",
                       schema="RAW", table="AUDIT_RESPONSE"):
    """Insert ONE summary row (one per question) into the audit table."""
    import snowflake.connector, datetime         # lazy imports (only when we actually save)

    # open a Snowflake connection — logs in with the TOKEN (not a password), as `role`
    conn = snowflake.connector.connect(account=account, user=user, password=token,
                                       role=role, warehouse=warehouse,
                                       database=database, schema=schema)
    cur = conn.cursor()                          # a cursor runs SQL
    try:
        insert = f"""
            INSERT INTO {database}.{schema}.{table}
              (asked_at,user_name, question, agent, role_used, final_answer, reasoning,
               planning_trace, tools_used, sql_queries, query_ids, num_rows,
               result_columns, model, raw_response)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """                                      # %s are placeholders filled below (safe)
        cur.execute(insert, (                    # run the INSERT with the real values
            datetime.datetime.now(),             # asked_at — the timestamp
            user,question, agent, role,               # who asked / which agent / which role
            summary.get("final_answer", ""),
            summary.get("reasoning", ""),
            summary.get("planning_trace", ""),
            summary.get("tools_used", ""),
            summary.get("sql_queries", ""),
            summary.get("query_ids", ""),
            _int_or_none(summary.get("num_rows")),   # NUMBER column -> int or None
            summary.get("result_columns", ""),
            summary.get("model", ""),            # the model name
            raw_response,                        # the FULL raw JSON stream
        ))
        conn.commit()                            # save the change permanently
        return 1                                 # one row written
    finally:
        cur.close()                              # always close the cursor...
        conn.close()                             # ...and the connection, even on error