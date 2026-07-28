"""
audit_extractor.py
==================================================================
Turns ONE Cortex Agent response into ONE clean audit row, and saves it to
Snowflake (HEALTHCARE_DB.RAW.AUDIT_RESPONSE).

app.py imports just two things from this file:
    summarize_audit(raw_stream)  -> a dict of facts about the question
    save_audit_summary(...)      -> INSERT that dict as one row

Everything else here is a helper for those two. You never run this file
directly — app.py imports it automatically.
==================================================================
"""

import json


# =========================================================================== #
# COST RATES  (used only to estimate est_cost_usd per question)
# -------------------------------------------------------------
# Snowflake bills Cortex in "AI Credits per 1,000,000 tokens" (a different rate
# for each model), and each AI Credit costs a fixed dollar amount.
#   • Token counts saved below are EXACT (straight from the response metadata).
#   • The dollar figure is an ESTIMATE using the two rates here.
#
# Set for an Opus-tier Claude model (3.00 credits/1M input, 15.00 credits/1M
# output) at $2.00 per AI Credit (global routing):
#      input : 3.00 / 1000 * 2.00 = 0.006 per 1K tokens
#      output: 15.00 / 1000 * 2.00 = 0.030 per 1K tokens
#   Sonnet model instead (1.80 / 9.00 credits)? use 0.0036 and 0.018.
#   Regional routing ($2.20/credit)?            use 0.0066 and 0.033.
# =========================================================================== #
USD_PER_1K_INPUT_TOKENS = 0.006
USD_PER_1K_OUTPUT_TOKENS = 0.030


# =========================================================================== #
# STEP 1 — build_audit(): read the streamed response into per-event rows.
# This is the low-level parser; summarize_audit() (Step 4) sits on top of it.
# =========================================================================== #
# Every audit row has these keys (blank when unused) so the shape is consistent.
COLUMNS = ["sequence_number", "event", "status", "message", "reasoning",
           "tool_name", "tool_type", "tool_use_id", "sql", "semantic_model",
           "pruning_question", "query_id", "num_rows", "columns", "model"]


def build_audit(raw_stream: str) -> list:
    """Parse the raw event/data stream into a list of per-event dicts."""
    rows = []
    current_event = None                        # remembers the latest "event:" label

    for line in raw_stream.splitlines():        # go through the stream line by line
        line = line.strip()
        if not line:
            continue

        if line.startswith("event:"):           # a LABEL line -> remember it
            current_event = line[len("event:"):].strip().lower()
            continue
        if not line.startswith("data:"):         # not a content line -> skip
            continue
        payload = line[len("data:"):].strip()    # the JSON text after "data:"
        if payload in ("[DONE]", ""):            # end marker / blank -> skip
            continue
        try:
            obj = json.loads(payload)            # JSON text -> Python dict
        except json.JSONDecodeError:
            continue

        ev = current_event or ""
        seq = obj.get("sequence_number")

        # ---- sort this event into an audit row, based on its label ----
        if ev == "response.status":              # a planning / reviewing status message
            rows.append(_row(seq, ev, status=obj.get("status"),
                             message=obj.get("message")))

        elif ev == "response.thinking":          # the agent's reasoning (full block)
            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                rows.append(_row(seq, ev, reasoning=txt.strip()))

        elif ev == "response.tool_use":          # the agent ran a tool / SQL
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
                                 message=obj.get("message"),
                                 query_id=details.get("QueryID")))

        elif ev in ("response.tool_result", "response.table"):   # the query RESULT (rows)
            info = _result_info(obj)
            if info:
                rows.append(_row(seq, ev, **info))

        elif ev == "response.text":              # the final consolidated answer
            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                rows.append(_row(seq, ev, answer=txt.strip()))

    return rows


def _row(seq, event, **kw):
    """Build one row with every column present (blank if unused), then fill kw."""
    row = {c: "" for c in COLUMNS}
    row["sequence_number"] = seq if seq is not None else ""
    row["event"] = event
    for k, v in kw.items():
        if v is not None:
            row[k] = v
    return row


def _one_line(sql):
    """Squash a multi-line SQL string onto one clean line (or return '')."""
    if isinstance(sql, str) and sql.strip():
        return " ".join(sql.split())
    return ""


def _result_info(obj):
    """Pull query_id, row count, and column names out of a result event."""
    rs = obj.get("result_set")                  # response.table has result_set at top level
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
    cols = [c.get("name") for c in (meta.get("rowType") or []) if isinstance(c, dict)]
    return {"query_id": query_id or "",
            "num_rows": meta.get("numRows", ""),
            "columns": ", ".join(cols)}


# =========================================================================== #
# STEP 2 — find the MODEL name dynamically from the usage metadata.
# =========================================================================== #
def _find_model(node, found):
    """Recursively collect every 'model_name' value found in the response."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "model_name" and isinstance(v, str) and v.strip():
                found.add(v.strip())
            else:
                _find_model(v, found)
    elif isinstance(node, list):
        for item in node:
            _find_model(item, found)


def _extract_model(raw_stream: str) -> str:
    """Return the model name(s) from the stream's usage metadata (no hard-coding)."""
    models = set()
    for line in raw_stream.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            _find_model(json.loads(payload), models)
        except json.JSONDecodeError:
            continue
    return ", ".join(sorted(models))


# =========================================================================== #
# STEP 3 — TOKEN USAGE + COST (from usage.tokens_consumed in the metadata).
# =========================================================================== #
def _as_int(v):
    """Turn a value into an int (0 if it can't be converted)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _find_tokens_consumed(node):
    """Return the last 'tokens_consumed' list found anywhere in the object (or None)."""
    found = None
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "tokens_consumed" and isinstance(v, list):
                found = v
            else:
                deeper = _find_tokens_consumed(v)
                if deeper is not None:
                    found = deeper
    elif isinstance(node, list):
        for item in node:
            deeper = _find_tokens_consumed(item)
            if deeper is not None:
                found = deeper
    return found


def _extract_tokens(raw_stream: str) -> dict:
    """Pull exact input/output/total token counts + estimated cost from the stream."""
    last = None
    for line in raw_stream.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            tc = _find_tokens_consumed(json.loads(payload))
        except json.JSONDecodeError:
            continue
        if tc:
            last = tc                            # keep the FINAL usage block
    if not last:                                # older responses may have no usage
        return {"input_tokens": None, "output_tokens": None,
                "total_tokens": None, "est_cost_usd": None}

    inp = sum(_as_int((e.get("input_tokens") or {}).get("total"))
              for e in last if isinstance(e, dict))
    out = sum(_as_int((e.get("output_tokens") or {}).get("total"))
              for e in last if isinstance(e, dict))
    cost = round(inp / 1000 * USD_PER_1K_INPUT_TOKENS
                 + out / 1000 * USD_PER_1K_OUTPUT_TOKENS, 6)
    return {"input_tokens": inp, "output_tokens": out,
            "total_tokens": inp + out, "est_cost_usd": cost}


# =========================================================================== #
# STEP 4 — summarize_audit(): collapse everything into ONE row per question.
# =========================================================================== #
def summarize_audit(raw_stream: str) -> dict:
    """Return a single dict of facts for the whole question (becomes one table row)."""
    rows = build_audit(raw_stream)
    final_answer, reasonings, planning = "", [], []
    sqls, query_ids, tools = [], [], []
    num_rows, result_columns = "", ""

    for r in rows:                              # walk the per-event rows, gather facts
        ev = r.get("event", "")
        if ev == "response.text":
            if r.get("answer"):
                final_answer = r["answer"]      # the final answer
        elif ev == "response.thinking":
            if r.get("reasoning"):
                reasonings.append(r["reasoning"])
        elif ev == "response.status":
            m = r.get("message", "")
            if m and (not planning or planning[-1] != m):
                planning.append(m)              # planning messages (no repeats)
        elif ev == "response.tool_use":
            if r.get("sql") and r["sql"] not in sqls:
                sqls.append(r["sql"])           # each unique SQL
            if r.get("tool_name") and r["tool_name"] not in tools:
                tools.append(r["tool_name"])
        elif ev in ("response.tool_result", "response.table"):
            if r.get("query_id") and r["query_id"] not in query_ids:
                query_ids.append(r["query_id"])
            if r.get("num_rows") not in ("", None):
                num_rows = r["num_rows"]
            if r.get("columns"):
                result_columns = r["columns"]

    return {
        "final_answer": final_answer,
        "reasoning": "\n".join(reasonings),
        "planning_trace": " → ".join(planning),        # Planning → Reviewing → ...
        "tools_used": ", ".join(tools),
        "sql_queries": "\n\n".join(sqls),              # all SQL, separated by blank lines
        "query_ids": ", ".join(query_ids),
        "num_rows": num_rows,
        "result_columns": result_columns,
        "model": _extract_model(raw_stream),           # model, read from metadata
        **_extract_tokens(raw_stream),                 # input_tokens, output_tokens, total_tokens, est_cost_usd
    }


# =========================================================================== #
# STEP 5 — save_audit_summary(): INSERT that one row into Snowflake.
# =========================================================================== #
def _int_or_none(v):
    """Turn '' or a bad value into None so a NUMBER column accepts it."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def save_audit_summary(summary, question, agent, role, account, user, token, raw_response="",
                       user_name=None,
                       warehouse="HEALTHCARE_WH", database="HEALTHCARE_DB",
                       schema="RAW", table="AUDIT_RESPONSE"):
    """Insert ONE summary row (one per question) into the audit table.

    `user`      = the Snowflake LOGIN (owner of the shared token) — for the connection.
    `user_name` = WHO to record in the user_name column (the person who asked).
                  If not given, it falls back to `user`.
    """
    import snowflake.connector, datetime         # lazy imports (only when we actually save)

    # Log in with the TOKEN as the password (bypasses MFA), acting as `role`.
    conn = snowflake.connector.connect(account=account, user=user, password=token,
                                       role=role, warehouse=warehouse,
                                       database=database, schema=schema)
    cur = conn.cursor()
    try:
        insert = f"""
            INSERT INTO {database}.{schema}.{table}
              (asked_at, user_name, question, agent, role_used, final_answer, reasoning,
               planning_trace, tools_used, sql_queries, query_ids, num_rows,
               result_columns, model, input_tokens, output_tokens, total_tokens,
               est_cost_usd, raw_response)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """                                      # %s are safe placeholders, filled below
        cur.execute(insert, (
            datetime.datetime.now(),             # asked_at
            user_name or user,                   # user_name = who asked (falls back to login)
            question, agent, role,
            summary.get("final_answer", ""),
            summary.get("reasoning", ""),
            summary.get("planning_trace", ""),
            summary.get("tools_used", ""),
            summary.get("sql_queries", ""),
            summary.get("query_ids", ""),
            _int_or_none(summary.get("num_rows")),
            summary.get("result_columns", ""),
            summary.get("model", ""),
            _int_or_none(summary.get("input_tokens")),   # exact input tokens
            _int_or_none(summary.get("output_tokens")),  # exact output tokens
            _int_or_none(summary.get("total_tokens")),   # input + output
            summary.get("est_cost_usd"),                 # estimated $ (from the rates on top)
            raw_response,                                # the FULL raw JSON stream
        ))
        conn.commit()                            # save the row permanently
        return 1
    finally:
        cur.close()                              # always close, even on error
        conn.close()