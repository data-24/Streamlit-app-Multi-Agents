-- =====================================================================
-- CREATE ONE SNOWFLAKE USER PER PERSON who uses the app.
-- Each person then logs into the app with THEIR OWN username + token,
-- so the audit table's USER_NAME column shows who really asked.
--
-- Run in a Snowsight worksheet as ACCOUNTADMIN.
-- Repeat the CREATE USER block for each additional person.
-- =====================================================================

USE ROLE ACCOUNTADMIN;

-- ---------------------------------------------------------------------
-- 1) The role the app runs as (already exists in your setup: READER_ROLE).
--    It needs to reach the agent + write the audit row. If READER_ROLE
--    already has these from earlier scripts, these grants are harmless
--    (they just re-confirm them).
-- ---------------------------------------------------------------------
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER            TO ROLE READER_ROLE;
GRANT USAGE  ON WAREHOUSE HEALTHCARE_WH              TO ROLE READER_ROLE;
GRANT USAGE  ON DATABASE  HEALTHCARE_DB              TO ROLE READER_ROLE;
GRANT USAGE  ON SCHEMA    HEALTHCARE_DB.GOLD         TO ROLE READER_ROLE;
GRANT USAGE  ON SCHEMA    HEALTHCARE_DB.RAW          TO ROLE READER_ROLE;
GRANT USAGE  ON AGENT     HEALTHCARE_DB.GOLD.HEALTHCARE_AGENT TO ROLE READER_ROLE;
GRANT INSERT ON TABLE     HEALTHCARE_DB.RAW.AUDIT_RESPONSE    TO ROLE READER_ROLE;

-- ---------------------------------------------------------------------
-- 2) Create a user for each person.  --- PERSON 1 ---
--    MUST_CHANGE_PASSWORD forces them to set their own password on first
--    login. DEFAULT_ROLE is the NON-admin app role (never ACCOUNTADMIN).
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS Priyanka
    PASSWORD          = 'TempPassw0rd!Change'      -- temporary; they change it
    LOGIN_NAME        = 'Priyanka'
    DISPLAY_NAME      = 'Priyanka Pandey'
    EMAIL             = 'pndy36@gmail.com'
    MUST_CHANGE_PASSWORD = TRUE
    DEFAULT_ROLE      = READER_ROLE
    DEFAULT_WAREHOUSE = HEALTHCARE_WH;
GRANT ROLE READER_ROLE TO USER Priyanka;

-- --- PERSON 2 --- (copy this block for every extra person) -----------
USE ROLE ACCOUNTADMIN;

-- remove the old one (this also drops its old tokens)
DROP USER IF EXISTS ANAND_JHA;

-- create it fresh
CREATE USER ANAND_JHA
    LOGIN_NAME        = 'ANAND_JHA'
    DISPLAY_NAME      = 'Anand Jha'
    EMAIL             = 'analyticswithanand@gmail.com'
    PASSWORD          = 'TempPassw0rd!Change'
    MUST_CHANGE_PASSWORD = FALSE
    DEFAULT_ROLE      = READER_ROLE
    DEFAULT_WAREHOUSE = HEALTHCARE_WH;

-- grant the role (required — the token restriction needs this)
GRANT ROLE READER_ROLE TO USER ANAND_JHA;

-- make ANAND_JHA's OWN token (this is the one for the app)
ALTER USER ANAND_JHA ADD PROGRAMMATIC ACCESS TOKEN cortex_token_anand
    ROLE_RESTRICTION = READER_ROLE
    DAYS_TO_EXPIRY   = 30;

-- ---------------------------------------------------------------------
-- 3) Each person makes their OWN access token (do this signed in AS them,
--    OR you can generate it for them). In a worksheet:
--
--    ALTER USER ROHAN ADD PROGRAMMATIC ACCESS TOKEN cortex_app_token
--        ROLE_RESTRICTION = READER_ROLE
--        DAYS_TO_EXPIRY   = 30;
--
--    Snowflake prints the token ONCE — copy it. In the app's
--    "Connection settings", that person types:
--        User  = ROHAN
--        Token = (the token above)
--    From then on every question they ask is stamped with USER_NAME = ROHAN.
-- ---------------------------------------------------------------------

-- Check the users exist:
SHOW USERS;


   
GRANT ROLE READER_ROLE TO USER Priyanka;
ALTER USER Priyanka ADD PROGRAMMATIC ACCESS TOKEN cortex_token_new1
ROLE_RESTRICTION = READER_ROLE
DAYS_TO_EXPIRY   = 30;
--------------------------------------------------------------------------------------------------------
GRANT ROLE READER_ROLE TO USER ANAND_JHA;

ALTER USER ANAND_JHA ADD PROGRAMMATIC ACCESS TOKEN cortex_token_anand5
       ROLE_RESTRICTION = READER_ROLE  DAYS_TO_EXPIRY = 30;


    GRANT ROLE READER_ROLE TO USER ANAND_JHA;
    GRANT ROLE READER_ROLE TO USER ANAND_JHA;
    show grants to user anand_jha;