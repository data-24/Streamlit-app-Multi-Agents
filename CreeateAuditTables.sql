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







