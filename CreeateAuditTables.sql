-- =====================================================================
-- AUDIT TABLE for Cortex Multi Agent Studio  —  ONE ROW PER QUESTION
-- Run this ONCE in a Snowsight worksheet (as ACCOUNTADMIN or the RAW-schema owner).
-- CREATE OR REPLACE rebuilds the table with the new (summary) shape.
-- =====================================================================

CREATE OR REPLACE TABLE HEALTHCARE_DB.RAW.AUDIT_RESPONSE (
    audit_id        STRING DEFAULT UUID_STRING(),  -- one id per question
    asked_at        TIMESTAMP_NTZ,                 -- when it was asked
    user_name       STRING,                        -- WHO asked  <-- key column
    question        STRING,
    agent           STRING,
    role_used       STRING,
    final_answer    STRING,
    reasoning       STRING,
    planning_trace  STRING,
    tools_used      STRING,
    sql_queries     STRING,
    query_ids       STRING,
    num_rows        NUMBER,
    result_columns  STRING,
    model           STRING,                        -- read from usage metadata
    raw_response    STRING,                        -- full raw stream
    loaded_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
 

-- ---- Let the app's role write to it (CREATE OR REPLACE drops old grants, so re-run) ----



USE ROLE ACCOUNTADMIN;
 
CREATE ROLE IF NOT EXISTS READER_ROLE;
 
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER            TO ROLE READER_ROLE;
GRANT USAGE  ON WAREHOUSE HEALTHCARE_WH              TO ROLE READER_ROLE;
GRANT USAGE  ON DATABASE  HEALTHCARE_DB              TO ROLE READER_ROLE;
GRANT USAGE  ON SCHEMA    HEALTHCARE_DB.GOLD         TO ROLE READER_ROLE;
GRANT USAGE  ON SCHEMA    HEALTHCARE_DB.RAW          TO ROLE READER_ROLE;
GRANT USAGE  ON AGENT     HEALTHCARE_DB.GOLD.HEALTHCARE_AGENT TO ROLE READER_ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA HEALTHCARE_DB.GOLD TO ROLE READER_ROLE;
GRANT INSERT ON TABLE    HEALTHCARE_DB.RAW.AUDIT_RESPONSE    TO ROLE READER_ROLE;
GRANT SELECT ON TABLE    HEALTHCARE_DB.RAW.AUDIT_RESPONSE    TO ROLE READER_ROLE;


-- ---- Check after asking a few questions in the app ----
-- SELECT asked_at, question, num_rows, final_answer FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE ORDER BY asked_at DESC;

---SELECT asked_at, question, model FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE ORDER BY asked_at DESC;
select *  FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE
ORDER BY asked_at DESC;




-- =====================================================================
-- Add token-usage + cost columns to the audit table.
-- Run once in a Snowsight worksheet (keeps your existing rows).
-- =====================================================================

ALTER TABLE HEALTHCARE_DB.RAW.AUDIT_RESPONSE
    ADD COLUMN IF NOT EXISTS input_tokens  NUMBER;        -- tokens the model READ (prompt + context)
ALTER TABLE HEALTHCARE_DB.RAW.AUDIT_RESPONSE
    ADD COLUMN IF NOT EXISTS output_tokens NUMBER;        -- tokens the model WROTE (the answer)
ALTER TABLE HEALTHCARE_DB.RAW.AUDIT_RESPONSE
    ADD COLUMN IF NOT EXISTS total_tokens  NUMBER;        -- input + output (total taken/used)
ALTER TABLE HEALTHCARE_DB.RAW.AUDIT_RESPONSE
    ADD COLUMN IF NOT EXISTS est_cost_usd  NUMBER(18,6);  -- estimated $ spent (from your rate)



    select *  FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE
ORDER BY asked_at DESC;

SELECT asked_at, user_name, question, input_tokens, output_tokens, total_tokens, est_cost_usd
FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE ORDER BY asked_at DESC LIMIT 5;
---truncate table HEALTHCARE_DB.RAW.AUDIT_RESPONSE;


-- Check per-question usage:
-- SELECT asked_at, user_name, question, input_tokens, output_tokens,
--        total_tokens, est_cost_usd
-- FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE
-- ORDER BY asked_at DESC;

-- Total spend per user:
-- SELECT user_name, SUM(total_tokens) AS tokens, SUM(est_cost_usd) AS spend
-- FROM HEALTHCARE_DB.RAW.AUDIT_RESPONSE GROUP BY user_name ORDER BY spend DESC;




