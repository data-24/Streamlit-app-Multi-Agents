# ❄️ Cortex Multi Agent Studio

A local **Streamlit** app that lets a non‑technical user talk to **Snowflake Cortex Agents** — pick a role, pick an agent (e.g. Healthcare or Finance), and ask questions in plain English. The app shows the answer and can optionally show the data table, the agent's thinking steps, and the SQL it wrote. Every question is automatically recorded in a Snowflake **audit table**, including *who asked it*.

Runs in VS Code on your own computer — no Streamlit‑in‑Snowflake required.

---

## ✨ Features

- 🎭 **Role & agent pickers** in the sidebar; the header shows the selected agent (e.g. "Healthcare Agent").
- 💬 **Plain‑English questions**, with clickable example questions.
- 🔀 **Independent toggles**: show data table · show thinking steps · show SQL · debug (raw stream).
- 🧾 **Per‑user audit logging**: one row per question saved to Snowflake — question, answer, SQL, model, and the user's name — fully automatic.
- 🔐 **Least privilege**: the app runs as a non‑admin role and authenticates with a Programmatic Access Token (PAT).

---

## 📁 Project structure

```
.
├── app.py                     # The application (run this)
├── appexplained.py            # Fully commented copy for teaching/reading
├── audit_extractor.py         # Builds & saves one audit row per question
├── requirements.txt           # Python dependencies
├── CreateAuditTables.sql      # Creates HEALTHCARE_DB.RAW.AUDIT_RESPONSE
├── CreateUser_StreamlitAPP.sql# Creates one Snowflake user per person
└── docs/
    └── Cortex_Multi_Agent_Studio_Student_Guide.docx
```

> **Important:** `app.py` and `audit_extractor.py` must live in the **same folder** — `app.py` imports `audit_extractor`.

---

## ✅ Prerequisites

- **VS Code** and **Python 3.12**
- A **Snowflake account** (ACCOUNTADMIN for the one‑time setup)
- A **Cortex Agent** already built (e.g. `HEALTHCARE_DB.GOLD.HEALTHCARE_AGENT`) over a semantic view
- A **warehouse** (e.g. `HEALTHCARE_WH`)

---

## 🚀 Getting started

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 2. Snowflake setup (run once in a Snowsight worksheet, as ACCOUNTADMIN)

1. Run **`CreateAuditTables.sql`** — creates the audit table (with a `user_name` column) and grants.
2. Run **`CreateUser_StreamlitAPP.sql`** — creates one Snowflake user per person, granted `READER_ROLE`.
3. Give each user their **own** token:

   ```sql
   ALTER USER PRIYANKA ADD PROGRAMMATIC ACCESS TOKEN cortex_token
       ROLE_RESTRICTION = READER_ROLE
       DAYS_TO_EXPIRY   = 30;
   ```

   Copy the printed `token_secret` (shown **once**).

### 3. Run the app

```bash
python -m streamlit run app.py
```

Open the browser tab, then in **⚙️ Connection settings** enter:

| Field | Value |
|---|---|
| Account | your account identifier, e.g. `ABC1234-XY56789` |
| User | the person's **NAME** from `SHOW USERS` (e.g. `PRIYANKA`) |
| Access token (PAT) | that user's `token_secret` |
| Role | `READER_ROLE` |

Ask a question — the answer appears, and one audit row is saved.

---

## 🧾 The audit table

Every question is saved to `HEALTHCARE_DB.RAW.AUDIT_RESPONSE` (one row per question). To view recent activity:

```sql
SELECT asked_at, user_name, question, num_rows, final_answer
FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE
ORDER BY asked_at DESC
LIMIT 10;
```

Each row captures: who asked (`user_name`), the question, agent and role, the final answer, the reasoning and planning trace, every SQL query and its query id, row count, result columns, the model (read dynamically), and the full raw response.

---

## 🔑 Key concepts

- **Two logins:** the agent call authenticates with the token alone (`Bearer` header); the audit save opens a Snowflake connection with `user + token` together, which Snowflake requires to match.
- **A PAT belongs to one user.** Create each person's token with `ALTER USER <name> ADD PROGRAMMATIC ACCESS TOKEN`. The Snowsight "Generate token" button always makes a token for *you* (the logged‑in admin).
- **Use the NAME**, not the first name / email / login name, in `GRANT`, `ALTER USER`, and the app's User box.

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---|---|
| Blank white screen | Use lazy imports (import heavy libs inside functions). |
| `pip` / `streamlit` not recognized | Use `python -m pip …` and `python -m streamlit run app.py`. |
| `ModuleNotFoundError: audit_extractor` | Keep `audit_extractor.py` beside `app.py`. |
| Agent answers but audit says "token is invalid" | Token doesn't belong to the User in the box — use that user's `ALTER USER … ADD PROGRAMMATIC ACCESS TOKEN` token. |
| `user_name` is NULL on new rows | Save the file, then fully restart the app (`Ctrl+C`, run again). |

See **`docs/Cortex_Multi_Agent_Studio_Student_Guide.docx`** for the full step‑by‑step guide.

---

## ⚠️ Security

- Never commit tokens or passwords. Tokens are entered in the app's UI at runtime — they are **not** stored in any file in this repo.
- `.gitignore` excludes Python caches and any local secrets.

---

*Built as a teaching project for Snowflake Cortex Agents.*
