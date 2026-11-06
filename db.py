"""
Database connectivity and query execution layer for Project 7.
Supports MySQL (via mysql-connector-python or PyMySQL) using environment variables
and provides automatic SQLite initialization from schema_and_seed.sql for instant testing.
All queries use parameterized SQL to prevent SQL injection.
"""
import os
import re
import sqlite3
from config import Config


class DatabaseError(Exception):
    """Custom exception for database connectivity and constraint errors."""
    pass


def get_connection(db_path_override=None):
    """
    Returns an active database connection based on Config.DB_ENGINE.
    If DB_ENGINE == 'mysql', connects to MySQL using environment credentials.
    Otherwise, connects to local SQLite database and initializes schema if empty.
    """
    engine = Config.DB_ENGINE
    if engine == "mysql" and not db_path_override:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=Config.MYSQL_HOST,
                port=Config.MYSQL_PORT,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                database=Config.MYSQL_DATABASE,
            )
            return conn, "mysql"
        except Exception as e:
            raise DatabaseError(f"MySQL connection failed: {str(e)}")
    else:
        target_path = db_path_override or Config.SQLITE_DB_PATH
        try:
            conn = sqlite3.connect(target_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn, "sqlite"
        except Exception as e:
            raise DatabaseError(f"SQLite connection failed: {str(e)}")


def init_sqlite_from_sql_file(sql_file_path=None, db_path_override=None):
    """
    Initializes the SQLite database using the MySQL schema_and_seed.sql script,
    adapting MySQL AUTO_INCREMENT syntax to SQLite compatibility so the exact
    same seed data powers both engines.
    """
    if sql_file_path is None:
        sql_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "schema_and_seed.sql"
        )
    conn, _ = get_connection(db_path_override=db_path_override)
    try:
        with open(sql_file_path, "r", encoding="utf-8") as f:
            raw_sql = f.read()

        # Adapt MySQL DDL specifics for SQLite execution
        lines = []
        for line in raw_sql.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("CREATE DATABASE") or stripped.upper().startswith("USE "):
                continue
            if stripped.upper().startswith("INDEX "):
                continue
            line = re.sub(r"INT\s+PRIMARY\s+KEY\s+AUTO_INCREMENT", "INTEGER PRIMARY KEY AUTOINCREMENT", line, flags=re.I)
            lines.append(line)

        cleaned_sql = "\n".join(lines)
        # Remove trailing comma before closing paren caused by stripped INDEX lines
        cleaned_sql = re.sub(r",\s*\n\s*\);", "\n);", cleaned_sql)

        conn.executescript(cleaned_sql)
        conn.commit()
    except Exception as e:
        conn.close()
        raise DatabaseError(f"Failed to initialize database from SQL script: {str(e)}")
    finally:
        conn.close()


def execute_query(query, params=(), fetch=True, db_path_override=None):
    """
    Executes a parameterized SQL query safely across MySQL or SQLite.
    Returns list of dicts if fetch=True, or dict with lastrowid and rowcount if fetch=False.
    """
    conn, engine = get_connection(db_path_override=db_path_override)
    try:
        if engine == "mysql":
            cursor = conn.cursor(dictionary=True)
            # Ensure %s placeholders for MySQL
            mysql_query = query.replace("?", "%s")
            cursor.execute(mysql_query, params)
            if fetch:
                rows = cursor.fetchall()
                return rows
            else:
                conn.commit()
                return {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}
        else:
            cursor = conn.cursor()
            sqlite_query = query.replace("%s", "?")
            cursor.execute(sqlite_query, params)
            if fetch:
                rows = [dict(r) for r in cursor.fetchall()]
                return rows
            else:
                conn.commit()
                return {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}
    except Exception as e:
        conn.rollback()
        raise DatabaseError(str(e))
    finally:
        conn.close()
