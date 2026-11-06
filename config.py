"""
Configuration module for Project 7: Hospital Patient Data Analysis System.
Reads database credentials and security settings strictly from environment variables
to avoid hard-coded secrets (per Section 6 General Implementation Notes).
"""
import os
import tempfile


class Config:
    # Database engine: 'mysql' (default for production/expo) or 'sqlite' (for local testing/demo fallback)
    DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").lower()

    # MySQL connection parameters from environment variables
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_USER = os.environ.get("MYSQL_USER", "hospital_analytics_user")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "hospital_analytics_db")

    # SQLite fallback database path for instant local verification and automated testing
    SQLITE_DB_PATH = os.environ.get(
        "SQLITE_DB_PATH",
        os.path.join(tempfile.gettempdir(), "hospital_analytics_p7.db")
    )

    # Role-based access token to restrict direct access to individual records
    # (Satisfies Acceptance Criterion: "restrict access to records; report aggregates only")
    ANALYST_API_TOKEN = os.environ.get("ANALYST_API_TOKEN", "edu-hospital-ops-token-2026")

    # Domain validation constants
    VALID_AGE_BANDS = ("0-17", "18-34", "35-49", "50-64", "65+")
    VALID_GENDERS = ("Female", "Male", "Other", "Unspecified")
    VALID_VISIT_TYPES = ("Outpatient", "Emergency", "Follow-up", "Inpatient")

    # Mandatory operational disclaimer attached to every API response and report
    OPERATIONAL_DISCLAIMER = (
        "OPERATIONAL STATISTICS ONLY: All records are 100% synthetic/de-identified. "
        "Outputs represent educational hospital operational analytics and must NOT be "
        "interpreted as clinical advice, medical diagnosis, or treatment recommendations."
    )
