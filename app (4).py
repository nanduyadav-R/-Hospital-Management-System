"""
================================================================================
 HOSPITAL PATIENT DATA ANALYSIS SYSTEM — ALL-IN-ONE FULL WEB APPLICATION (app.py)
 Project 7 | Difficulty: Intermediate | Python + Flask + Pandas + NumPy + Matplotlib

 Features:
  - Full Web Dashboard with Navigation Tabs (Overview, Visits, Patients,
    Departments, Charts Gallery, and Interactive Backend API Tester)
  - Full CRUD Operations (Create / Read / Update / Delete) for:
      * Visits      (GET, POST, PUT, DELETE + filtering by dept, type, dates)
      * Patients    (GET, POST, PUT, DELETE + filtering by age band, gender)
      * Departments (GET, POST, PUT, DELETE + workload & z-score stats)
  - Pandas & NumPy Statistical Analysis (Mean, Median, Std Dev, Z-scores,
    Month-over-Month % change, Linear Regression trend via np.polyfit)
  - 6 Matplotlib Operational Charts generated on-demand and displayed in UI

 Run with:
    py app.py
 Then open:
    http://localhost:5000/
================================================================================
"""

import os
import sys
import io
import re
import socket
import threading
import webbrowser
import sqlite3
import logging
from datetime import datetime
import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend safe for Flask threads
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from flask import Flask, jsonify, request, render_template_string, send_from_directory

# Windows UTF-8 stdout fix
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hospital_analytics")
logging.getLogger("matplotlib").setLevel(logging.WARNING)

# ------------------------------------------------------------------------------
# CONFIGURATION & CONSTANTS
# ------------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "hospital_analytics.db"))
CHARTS_DIR = os.environ.get("CHARTS_DIR", os.path.join(BASE_DIR, "charts"))
PORT = int(os.environ.get("PORT", 5000))
CHART_LOCK = threading.Lock()
os.makedirs(CHARTS_DIR, exist_ok=True)


def get_lan_ips():
    """Detect all local network (Wi-Fi / LAN / Hotspot) IPv4 addresses for this laptop."""
    ips = []
    # Method 1: UDP socket routing probe (works without internet access on active LAN/Wi-Fi)
    for target in [("8.8.8.8", 80), ("10.255.255.255", 1), ("192.168.1.1", 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
        except Exception:
            pass

    # Method 2: Hostname resolution fallback
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    return ips if ips else ["127.0.0.1"]

DISCLAIMER = (
    "OPERATIONAL STATISTICS ONLY — Not clinical advice, diagnosis, or treatment "
    "recommendations. All data is synthetic and de-identified."
)

VALID_AGE_BANDS = ["0-17", "18-34", "35-49", "50-64", "65+"]
VALID_GENDERS = ["M", "F", "Other", "Prefer not to say"]
VALID_VISIT_TYPES = ["Outpatient", "Inpatient", "Emergency", "Follow-up", "Teleconsult"]

PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# ------------------------------------------------------------------------------
# DATABASE HELPERS & INITIALIZATION
# ------------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def query_all(sql: str, params=()):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute_db(sql: str, params=()):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def init_database(reset_existing: bool = False):
    """Create tables, views, and seed initial synthetic data if empty (or if reset_existing=True)."""
    if reset_existing and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass
    with get_db() as conn:
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS departments (
            department_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            department_name TEXT NOT NULL UNIQUE,
            description     TEXT DEFAULT '',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS patients (
            patient_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            age_band     TEXT NOT NULL,
            gender       TEXT DEFAULT 'Prefer not to say',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS visits (
            visit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id    INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            visit_date    DATE NOT NULL,
            visit_type    TEXT NOT NULL,
            notes         TEXT DEFAULT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (department_id) REFERENCES departments(department_id)
        );

        DROP VIEW IF EXISTS vw_monthly_visits;
        CREATE VIEW vw_monthly_visits AS
        SELECT strftime('%Y-%m', visit_date) AS year_month,
               COUNT(*) AS total_visits
        FROM visits
        GROUP BY year_month
        ORDER BY year_month;

        DROP VIEW IF EXISTS vw_dept_workload;
        CREATE VIEW vw_dept_workload AS
        SELECT d.department_id,
               d.department_name,
               COALESCE(d.description, '') AS description,
               COUNT(v.visit_id) AS total_visits,
               COUNT(DISTINCT v.patient_id) AS unique_patients,
               SUM(CASE WHEN v.visit_type='Emergency' THEN 1 ELSE 0 END) AS emergency_visits,
               SUM(CASE WHEN v.visit_type='Outpatient' THEN 1 ELSE 0 END) AS outpatient_visits,
               SUM(CASE WHEN v.visit_type='Inpatient' THEN 1 ELSE 0 END) AS inpatient_visits,
               SUM(CASE WHEN v.visit_type='Follow-up' THEN 1 ELSE 0 END) AS followup_visits,
               SUM(CASE WHEN v.visit_type='Teleconsult' THEN 1 ELSE 0 END) AS teleconsult_visits
        FROM departments d
        LEFT JOIN visits v ON d.department_id = v.department_id
        GROUP BY d.department_id, d.department_name, d.description
        ORDER BY total_visits DESC, d.department_name ASC;

        DROP VIEW IF EXISTS vw_age_band_summary;
        CREATE VIEW vw_age_band_summary AS
        SELECT p.age_band,
               COUNT(v.visit_id) AS total_visits,
               COUNT(DISTINCT p.patient_id) AS unique_patients
        FROM patients p
        LEFT JOIN visits v ON p.patient_id = v.patient_id
        GROUP BY p.age_band;
        """)

        # Seed only if departments table is empty
        if cur.execute("SELECT COUNT(*) FROM departments").fetchone()[0] == 0:
            departments = [
                ("Cardiology", "Heart and cardiovascular system"),
                ("Orthopedics", "Bones, joints and musculoskeletal"),
                ("Neurology", "Brain, spinal cord and nervous system"),
                ("Pediatrics", "Children and adolescents"),
                ("General Medicine", "General consultations and primary care"),
                ("Dermatology", "Skin conditions"),
                ("Oncology", "Cancer screening and treatment support"),
                ("Emergency", "Acute and emergency care"),
                ("Gynecology", "Women's reproductive health"),
                ("ENT", "Ear, nose and throat"),
            ]
            cur.executemany(
                "INSERT INTO departments (department_name, description) VALUES (?, ?)",
                departments,
            )

            base_patients = [
                ("18-34", "M"), ("65+", "F"), ("50-64", "M"), ("35-49", "F"), ("0-17", "M"),
                ("18-34", "F"), ("65+", "M"), ("50-64", "F"), ("35-49", "M"), ("0-17", "F"),
                ("18-34", "M"), ("65+", "F"), ("50-64", "M"), ("35-49", "F"), ("0-17", "Other"),
                ("18-34", "F"), ("65+", "M"), ("50-64", "F"), ("35-49", "M"), ("0-17", "M"),
                ("65+", "F"), ("50-64", "M"), ("18-34", "F"), ("35-49", "M"), ("65+", "F"),
                ("18-34", "M"), ("50-64", "F"), ("35-49", "M"), ("0-17", "F"), ("65+", "M"),
                ("18-34", "F"), ("65+", "F"), ("50-64", "M"), ("35-49", "F"), ("0-17", "M"),
                ("18-34", "M"), ("65+", "F"), ("50-64", "M"), ("35-49", "F"), ("0-17", "F"),
            ]
            cur.executemany(
                "INSERT INTO patients (age_band, gender) VALUES (?, ?)",
                base_patients * 5,
            )

            import random
            random.seed(42)
            visits = []
            sample_notes = [
                "Routine checkup", "Initial consultation", "Lab results review",
                "Post-discharge follow-up", "Acute symptom evaluation", "Medication refill"
            ]
            for month in range(1, 13):
                m_str = f"2025-{month:02d}" if month <= 10 else f"2024-{month:02d}"
                count = random.randint(20, 26)
                for _ in range(count):
                    day = random.randint(1, 28)
                    visits.append((
                        random.randint(1, 40),
                        random.randint(1, 10),
                        f"{m_str}-{day:02d}",
                        random.choices(VALID_VISIT_TYPES, weights=[40, 10, 20, 20, 10])[0],
                        random.choice(sample_notes),
                    ))
            cur.executemany(
                "INSERT INTO visits (patient_id, department_id, visit_date, visit_type, notes) VALUES (?, ?, ?, ?, ?)",
                visits,
            )
            conn.commit()


# ------------------------------------------------------------------------------
# PANDAS / NUMPY DATAFRAME & MATPLOTLIB CHART GENERATOR
# ------------------------------------------------------------------------------
def get_dataframe():
    rows = query_all("""
        SELECT v.visit_id, v.patient_id, v.department_id,
               d.department_name, v.visit_date, v.visit_type,
               COALESCE(v.notes, '') AS notes,
               p.age_band, p.gender
        FROM visits v
        JOIN departments d ON v.department_id = d.department_id
        JOIN patients    p ON v.patient_id    = p.patient_id
    """)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["visit_date"] = pd.to_datetime(df["visit_date"], errors="coerce")
    df = df.dropna(subset=["visit_date"])
    df["year_month"] = df["visit_date"].dt.to_period("M").astype(str)
    df["day_of_week"] = df["visit_date"].dt.day_name()
    return df


def generate_all_charts():
    """Generate all 6 operational Matplotlib charts and save to CHARTS_DIR (thread-safe)."""
    with CHART_LOCK:
        return _generate_all_charts_locked()


def _generate_all_charts_locked():
    df = get_dataframe()
    if df.empty:
        return []

    generated = []

    # 1. Department-wise Workload (Horizontal Bar)
    fig, ax = plt.subplots(figsize=(9, 5))
    grp = df.groupby("department_name")["visit_id"].count().sort_values()
    bars = ax.barh(grp.index, grp.values, color=PALETTE[:len(grp)])
    ax.bar_label(bars, padding=3, fontsize=9)
    ax.set_title("1. Department-wise Workload (Total Visits)", fontweight="bold")
    ax.set_xlabel("Number of Visits")
    ax.set_xlim(0, max(grp.values) * 1.15 if len(grp) else 10)
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p1 = "dept_workload_bar.png"
    fig.savefig(os.path.join(CHARTS_DIR, p1), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p1)

    # 2. Monthly Patient Visit Trends + Linear Fit
    fig, ax = plt.subplots(figsize=(10, 5))
    m = df.groupby("year_month")["visit_id"].count().reset_index().sort_values("year_month")
    x_idx = np.arange(len(m))
    ax.plot(m["year_month"], m["visit_id"], marker="o", color="#1a3a5c", linewidth=2.2, label="Monthly Visits")
    if len(m) >= 2:
        slope, intercept = np.polyfit(x_idx, m["visit_id"].values, 1)
        trend_y = slope * x_idx + intercept
        ax.plot(m["year_month"], trend_y, linestyle="--", color="#C44E52", linewidth=1.8,
                label=f"Linear Trend (slope={slope:+.2f}/mo)")
    for i, val in enumerate(m["visit_id"]):
        ax.annotate(str(val), (m["year_month"].iloc[i], val), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_title("2. Monthly Patient Visit Trends & Linear Fit", fontweight="bold")
    ax.set_ylabel("Number of Visits")
    ax.set_xlabel("Month (YYYY-MM)")
    ax.legend()
    plt.xticks(rotation=45)
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p2 = "monthly_visits_line.png"
    fig.savefig(os.path.join(CHARTS_DIR, p2), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p2)

    # 3. Visit Type Distribution (Pie)
    fig, ax = plt.subplots(figsize=(7, 6.5))
    vt = df["visit_type"].value_counts()
    ax.pie(vt.values, labels=vt.index, autopct="%1.1f%%", colors=PALETTE[:len(vt)],
           startangle=140, wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    ax.set_title("3. Visit Type Distribution (%)", fontweight="bold")
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p3 = "visit_type_pie.png"
    fig.savefig(os.path.join(CHARTS_DIR, p3), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p3)

    # 4. Visits by Age Band (Vertical Bar)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ab = df["age_band"].value_counts().reindex(VALID_AGE_BANDS, fill_value=0)
    bars = ax.bar(ab.index, ab.values, color=PALETTE[:5])
    ax.bar_label(bars, padding=3, fontsize=9)
    ax.set_title("4. Visits by Patient Age Band", fontweight="bold")
    ax.set_xlabel("Age Band (Years)")
    ax.set_ylabel("Number of Visits")
    ax.set_ylim(0, max(ab.values) * 1.15 if len(ab) and max(ab.values) > 0 else 10)
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p4 = "age_band_bar.png"
    fig.savefig(os.path.join(CHARTS_DIR, p4), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p4)

    # 5. Total vs Emergency Visits per Department (Grouped Bar)
    fig, ax = plt.subplots(figsize=(10, 5))
    dept_tot = df.groupby("department_name")["visit_id"].count()
    dept_emg = df[df["visit_type"] == "Emergency"].groupby("department_name")["visit_id"].count()
    comp_df = pd.DataFrame({"Total": dept_tot, "Emergency": dept_emg}).fillna(0).sort_values("Total", ascending=False)
    x = np.arange(len(comp_df))
    w = 0.38
    b1 = ax.bar(x - w / 2, comp_df["Total"], width=w, label="Total Visits", color="#4C72B0")
    b2 = ax.bar(x + w / 2, comp_df["Emergency"], width=w, label="Emergency Visits", color="#C44E52")
    ax.bar_label(b1, padding=2, fontsize=8)
    ax.bar_label(b2, padding=2, fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(comp_df.index, rotation=35, ha="right")
    ax.set_title("5. Total vs. Emergency Visits by Department", fontweight="bold")
    ax.set_ylabel("Number of Visits")
    ax.legend()
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p5 = "dept_emergency_heatmap.png"
    fig.savefig(os.path.join(CHARTS_DIR, p5), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p5)

    # 6. Visit Volume by Day of Week
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow = df["day_of_week"].value_counts().reindex(days_order, fill_value=0)
    bars = ax.bar(dow.index, dow.values, color="#55A868")
    ax.bar_label(bars, padding=3, fontsize=9)
    ax.set_title("6. Visit Volume by Day of Week", fontweight="bold")
    ax.set_xlabel("Day of Week")
    ax.set_ylabel("Number of Visits")
    ax.set_ylim(0, max(dow.values) * 1.15 if len(dow) and max(dow.values) > 0 else 10)
    plt.xticks(rotation=25)
    fig.text(0.5, 0.01, DISCLAIMER, ha="center", fontsize=7, color="gray")
    p6 = "day_of_week_bar.png"
    fig.savefig(os.path.join(CHARTS_DIR, p6), bbox_inches="tight", dpi=130)
    plt.close(fig)
    generated.append(p6)

    return generated


# Initialize DB on import/startup
init_database()


# ------------------------------------------------------------------------------
# FLASK APPLICATION & JSON HELPERS
# ------------------------------------------------------------------------------
app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """Allow any laptop on the network to access the API and web resources smoothly."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def ok(data=None, msg="OK", status=200):
    return jsonify({
        "status": "success",
        "message": msg,
        "data": data,
        "disclaimer": DISCLAIMER
    }), status


def err(msg="Bad request", status=400, details=None):
    payload = {
        "status": "error",
        "message": msg,
        "disclaimer": DISCLAIMER
    }
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status


# ------------------------------------------------------------------------------
# FULL INTERACTIVE SINGLE-PAGE WEB APPLICATION (HTML / CSS / JS)
# ------------------------------------------------------------------------------
HTML_DASHBOARD = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hospital Patient Data Analysis System — 3D Interactive Edition</title>
  <style>
    :root[data-theme="dark"] {
      --bg-main: #060b19;
      --bg-secondary: #0b132b;
      --card-bg: rgba(15, 25, 50, 0.72);
      --card-border: rgba(56, 189, 248, 0.22);
      --card-glow: 0 18px 40px -12px rgba(0, 0, 0, 0.7), 0 0 25px rgba(14, 165, 233, 0.12);
      --text: #f1f5f9;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --primary-solid: #0284c7;
      --accent: #2dd4bf;
      --purple: #a855f7;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --input-bg: rgba(15, 23, 42, 0.85);
      --table-hover: rgba(56, 189, 248, 0.08);
      --table-th: rgba(15, 23, 42, 0.9);
      --border: rgba(148, 163, 184, 0.16);
    }
    :root[data-theme="light"] {
      --bg-main: #eef2f9;
      --bg-secondary: #ffffff;
      --card-bg: rgba(255, 255, 255, 0.88);
      --card-border: rgba(2, 132, 199, 0.22);
      --card-glow: 0 16px 35px -10px rgba(15, 23, 42, 0.12), 0 0 20px rgba(2, 132, 199, 0.08);
      --text: #0f172a;
      --muted: #475569;
      --primary: #0284c7;
      --primary-solid: #0369a1;
      --accent: #0d9488;
      --purple: #7e22ce;
      --success: #16a34a;
      --warning: #d97706;
      --danger: #dc2626;
      --input-bg: #ffffff;
      --table-hover: rgba(2, 132, 199, 0.06);
      --table-th: #f1f5f9;
      --border: rgba(15, 23, 42, 0.12);
    }

    * { box-sizing: border-box; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: var(--bg-main);
      color: var(--text);
      margin: 0;
      padding: 0;
      overflow-x: hidden;
      perspective: 1400px;
      transition: background 0.35s ease, color 0.35s ease;
    }

    /* Fullscreen Ambient 3D Background Canvas */
    #bg-3d-canvas {
      position: fixed;
      inset: 0;
      width: 100vw;
      height: 100vh;
      z-index: 0;
      pointer-events: none;
      opacity: 0.42;
    }

    .app-shell {
      position: relative;
      z-index: 1;
    }

    /* 3D Glassmorphic Header */
    header {
      background: linear-gradient(135deg, rgba(10, 22, 48, 0.92) 0%, rgba(17, 34, 68, 0.88) 100%);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      color: #f8fafc;
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      border-bottom: 1px solid rgba(56, 189, 248, 0.25);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    }
    .brand-wrap {
      display: flex;
      align-items: center;
      gap: 0.9rem;
    }
    /* 3D Rotating Medical Cube Logo */
    .cube-scene {
      width: 42px;
      height: 42px;
      perspective: 200px;
    }
    .cube {
      width: 100%;
      height: 100%;
      position: relative;
      transform-style: preserve-3d;
      animation: spinCube 9s infinite linear;
    }
    .cube-face {
      position: absolute;
      width: 42px;
      height: 42px;
      background: linear-gradient(135deg, rgba(56, 189, 248, 0.85), rgba(45, 212, 191, 0.85));
      border: 1.5px solid #e0f2fe;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      box-shadow: inset 0 0 12px rgba(255,255,255,0.4);
    }
    .cube-face.front  { transform: rotateY(  0deg) translateZ(21px); }
    .cube-face.right  { transform: rotateY( 90deg) translateZ(21px); }
    .cube-face.back   { transform: rotateY(180deg) translateZ(21px); }
    .cube-face.left   { transform: rotateY(-90deg) translateZ(21px); }
    .cube-face.top    { transform: rotateX( 90deg) translateZ(21px); }
    .cube-face.bottom { transform: rotateX(-90deg) translateZ(21px); }
    @keyframes spinCube {
      0%   { transform: rotateX(-18deg) rotateY(0deg); }
      50%  { transform: rotateX(18deg)  rotateY(180deg); }
      100% { transform: rotateX(-18deg) rotateY(360deg); }
    }

    header h1 {
      margin: 0;
      font-size: 1.38rem;
      background: linear-gradient(90deg, #ffffff, #38bdf8, #2dd4bf);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      letter-spacing: 0.01em;
    }
    header .subtitle { font-size: 0.8rem; color: #94a3b8; margin-top: 0.2rem; }
    .header-actions { display: flex; gap: 0.55rem; flex-wrap: wrap; align-items: center; }

    .disclaimer-bar {
      background: rgba(245, 158, 11, 0.14);
      color: #fbbf24;
      padding: 0.5rem 2rem;
      font-size: 0.8rem;
      border-bottom: 1px solid rgba(245, 158, 11, 0.3);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      backdrop-filter: blur(8px);
    }
    :root[data-theme="light"] .disclaimer-bar {
      background: #fffbeb;
      color: #92400e;
      border-bottom-color: #fde68a;
    }

    /* 3D Interactive Hero Stage */
    .hero-3d-wrapper {
      max-width: 1340px;
      margin: 1.25rem auto 0;
      padding: 0 2rem;
    }
    .hero-3d-stage {
      position: relative;
      border-radius: 16px;
      background: radial-gradient(circle at 70% 40%, rgba(14, 165, 233, 0.18), rgba(10, 18, 38, 0.92) 75%);
      border: 1px solid var(--card-border);
      box-shadow: var(--card-glow);
      overflow: hidden;
      display: grid;
      grid-template-columns: 1.05fr 1.35fr;
      min-height: 270px;
      transform-style: preserve-3d;
    }
    @media (max-width: 960px) {
      .hero-3d-stage { grid-template-columns: 1fr; }
    }
    .hero-3d-info {
      padding: 1.6rem 1.8rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      z-index: 2;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.3rem 0.75rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      background: rgba(56, 189, 248, 0.18);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.4);
      width: fit-content;
    }
    .hero-3d-info h2 {
      margin: 0.65rem 0 0.4rem;
      font-size: 1.55rem;
      color: #f8fafc;
      line-height: 1.25;
    }
    .hero-3d-info p {
      margin: 0 0 1rem;
      font-size: 0.88rem;
      color: #cbd5e1;
      line-height: 1.55;
    }
    .mode-switcher {
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
    }
    .mode-btn {
      padding: 0.45rem 0.8rem;
      border-radius: 8px;
      border: 1px solid rgba(56, 189, 248, 0.35);
      background: rgba(15, 23, 42, 0.75);
      color: #e2e8f0;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .mode-btn:hover {
      transform: translateY(-2px) scale(1.03);
      border-color: #38bdf8;
    }
    .mode-btn.active {
      background: linear-gradient(135deg, #0284c7, #0d9488);
      color: white;
      border-color: #7dd3fc;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.45);
    }
    .hero-canvas-box {
      position: relative;
      min-height: 260px;
      cursor: grab;
    }
    .hero-canvas-box:active { cursor: grabbing; }
    #hero-3d-canvas {
      width: 100%;
      height: 100%;
      display: block;
    }
    .canvas-hint {
      position: absolute;
      bottom: 10px;
      right: 14px;
      font-size: 0.74rem;
      color: rgba(226, 232, 240, 0.75);
      background: rgba(15, 23, 42, 0.65);
      padding: 3px 9px;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.2);
      pointer-events: none;
    }

    /* 3D Navigation Tabs */
    .nav-tabs {
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--border);
      padding: 0.4rem 2rem;
      margin-top: 1.25rem;
      display: flex;
      gap: 0.4rem;
      overflow-x: auto;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .nav-tab {
      padding: 0.7rem 1.15rem;
      border: 1px solid transparent;
      border-radius: 10px;
      background: transparent;
      color: var(--muted);
      font-weight: 600;
      font-size: 0.88rem;
      cursor: pointer;
      transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
      white-space: nowrap;
    }
    .nav-tab:hover {
      color: var(--primary);
      transform: translateY(-2px);
      background: var(--table-hover);
    }
    .nav-tab.active {
      color: #ffffff;
      background: linear-gradient(135deg, var(--primary-solid), var(--accent));
      box-shadow: 0 6px 18px -4px rgba(14, 165, 233, 0.55);
      transform: translateY(-1px);
    }

    .container { max-width: 1340px; margin: 0 auto; padding: 1.5rem 2rem 3.5rem; }

    /* 3D Perspective Tab Entrance Animation */
    .tab-pane {
      display: none;
      transform-origin: top center;
    }
    .tab-pane.active {
      display: block;
      animation: tabEnter3D 0.45s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }
    @keyframes tabEnter3D {
      0% {
        opacity: 0;
        transform: perspective(1200px) rotateX(-8deg) translateY(18px) scale(0.98);
      }
      100% {
        opacity: 1;
        transform: perspective(1200px) rotateX(0deg) translateY(0) scale(1);
      }
    }

    /* 3D Interactive Tilt KPI Grid */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 1.1rem;
      margin-bottom: 1.6rem;
    }
    .kpi-card {
      position: relative;
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      border-radius: 14px;
      padding: 1.25rem 1.35rem;
      box-shadow: var(--card-glow);
      border: 1px solid var(--card-border);
      transform-style: preserve-3d;
      transition: transform 0.18s ease-out, box-shadow 0.25s ease, border-color 0.25s ease;
      overflow: hidden;
    }
    .kpi-card::before {
      content: "";
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--primary), var(--accent), var(--purple));
    }
    .kpi-card:hover {
      border-color: var(--primary);
      box-shadow: 0 22px 45px -12px rgba(2, 132, 199, 0.35);
    }
    .kpi-card .kpi-icon {
      position: absolute;
      right: 1rem;
      top: 1rem;
      font-size: 1.8rem;
      opacity: 0.25;
      transform: translateZ(25px);
    }
    .kpi-card .label {
      font-size: 0.76rem;
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      transform: translateZ(15px);
    }
    .kpi-card .value {
      font-size: 2rem;
      font-weight: 800;
      color: var(--primary);
      margin: 0.35rem 0 0.2rem;
      transform: translateZ(30px);
      text-shadow: 0 4px 14px rgba(56, 189, 248, 0.25);
    }
    .kpi-card .sub {
      font-size: 0.78rem;
      color: var(--muted);
      transform: translateZ(12px);
    }

    /* 3D Glassmorphic Cards & Layout */
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(14px);
      border-radius: 14px;
      padding: 1.45rem;
      box-shadow: var(--card-glow);
      border: 1px solid var(--card-border);
      margin-bottom: 1.5rem;
      transition: transform 0.25s ease, box-shadow 0.25s ease;
    }
    .card:hover {
      box-shadow: 0 22px 48px -12px rgba(0, 0, 0, 0.5), 0 0 28px rgba(56, 189, 248, 0.16);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.8rem;
      margin-bottom: 1.1rem;
      padding-bottom: 0.8rem;
      border-bottom: 1px solid var(--border);
    }
    .card-header h2 {
      margin: 0;
      font-size: 1.12rem;
      color: var(--primary);
      display: flex;
      align-items: center;
      gap: 0.45rem;
    }

    .two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.5rem;
    }
    @media (max-width: 960px) {
      .two-col { grid-template-columns: 1fr; }
    }

    /* Forms & Inputs */
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.9rem;
      align-items: end;
    }
    .form-group { display: flex; flex-direction: column; gap: 0.35rem; }
    .form-group label { font-size: 0.78rem; font-weight: 600; color: var(--muted); }
    input, select, textarea {
      padding: 0.6rem 0.8rem;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 0.88rem;
      font-family: inherit;
      background: var(--input-bg);
      color: var(--text);
      transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
      transform: translateY(-1px);
    }

    /* 3D Tactile Buttons */
    .btn {
      padding: 0.58rem 1.05rem;
      border-radius: 8px;
      border: none;
      font-weight: 600;
      font-size: 0.85rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      text-decoration: none;
      transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.18s ease;
    }
    .btn:hover {
      transform: translateY(-2px) scale(1.02);
    }
    .btn:active { transform: translateY(1px) scale(0.99); }
    .btn-primary {
      background: linear-gradient(135deg, #0284c7, #2563eb);
      color: white;
      box-shadow: 0 6px 16px -3px rgba(2, 132, 199, 0.5);
    }
    .btn-success {
      background: linear-gradient(135deg, #10b981, #059669);
      color: white;
      box-shadow: 0 6px 16px -3px rgba(16, 185, 129, 0.45);
    }
    .btn-accent {
      background: linear-gradient(135deg, #14b8a6, #0d9488);
      color: white;
      box-shadow: 0 6px 16px -3px rgba(20, 184, 166, 0.45);
    }
    .btn-warning {
      background: linear-gradient(135deg, #f59e0b, #d97706);
      color: white;
      box-shadow: 0 6px 16px -3px rgba(245, 158, 11, 0.45);
    }
    .btn-danger {
      background: linear-gradient(135deg, #ef4444, #dc2626);
      color: white;
      box-shadow: 0 6px 16px -3px rgba(239, 68, 68, 0.4);
    }
    .btn-outline {
      background: rgba(148, 163, 184, 0.1);
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-sm { padding: 0.34rem 0.68rem; font-size: 0.78rem; border-radius: 6px; }

    /* Tables */
    .table-wrap { overflow-x: auto; border-radius: 10px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { text-align: left; padding: 0.72rem 0.8rem; border-bottom: 1px solid var(--border); }
    th {
      background: var(--table-th);
      color: var(--muted);
      font-weight: 700;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    tr { transition: transform 0.15s ease, background 0.15s ease; }
    tr:hover td { background: var(--table-hover); }
    .actions-cell { display: flex; gap: 0.4rem; white-space: nowrap; }

    /* Badges */
    .badge {
      padding: 0.24rem 0.65rem;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 700;
      display: inline-block;
      letter-spacing: 0.02em;
    }
    .badge-Emergency   { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); }
    .badge-Outpatient  { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }
    .badge-Inpatient   { background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); }
    .badge-Follow-up   { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
    .badge-Teleconsult { background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.35); }
    :root[data-theme="light"] .badge-Emergency   { background: #fee2e2; color: #b91c1c; }
    :root[data-theme="light"] .badge-Outpatient  { background: #dcfce7; color: #15803d; }
    :root[data-theme="light"] .badge-Inpatient   { background: #dbeafe; color: #1d4ed8; }
    :root[data-theme="light"] .badge-Follow-up   { background: #fef3c7; color: #b45309; }
    :root[data-theme="light"] .badge-Teleconsult { background: #f3e8ff; color: #6d28d9; }

    /* 3D Charts Gallery */
    .charts-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
      gap: 1.35rem;
    }
    @media (max-width: 600px) {
      .charts-grid { grid-template-columns: 1fr; }
    }
    .chart-box {
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 0.9rem;
      text-align: center;
      transform-style: preserve-3d;
      transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.28s ease;
    }
    .chart-box:hover {
      transform: perspective(900px) translateY(-6px) rotateX(2deg) scale(1.015);
      box-shadow: 0 20px 40px rgba(2, 132, 199, 0.3);
    }
    .chart-box img {
      max-width: 100%;
      height: auto;
      border-radius: 6px;
    }

    /* 3D Modal for Editing Records */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(6, 11, 25, 0.72);
      backdrop-filter: blur(8px);
      display: none;
      justify-content: center;
      align-items: center;
      z-index: 200;
      padding: 1rem;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      background: var(--bg-secondary);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      width: 100%;
      max-width: 520px;
      padding: 1.6rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
      animation: modalPop3D 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes modalPop3D {
      0% { opacity: 0; transform: perspective(800px) rotateX(-15deg) scale(0.9); }
      100% { opacity: 1; transform: perspective(800px) rotateX(0deg) scale(1); }
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.8rem;
      margin-bottom: 1rem;
    }
    .modal-header h3 { margin: 0; color: var(--primary); }
    .modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 0.6rem;
      margin-top: 1.25rem;
      padding-top: 0.8rem;
      border-top: 1px solid var(--border);
    }

    /* Toast Notification */
    #toast {
      position: fixed;
      bottom: 1.5rem;
      right: 1.5rem;
      padding: 0.88rem 1.35rem;
      border-radius: 10px;
      background: #1e293b;
      color: white;
      font-weight: 600;
      font-size: 0.88rem;
      box-shadow: 0 15px 30px rgba(0,0,0,0.45);
      transform: translateY(150%);
      transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 300;
    }
    #toast.show { transform: translateY(0); }
    #toast.success { background: linear-gradient(135deg, #10b981, #059669); }
    #toast.error   { background: linear-gradient(135deg, #ef4444, #b91c1c); }

    pre.json-box {
      background: #050811;
      color: #38bdf8;
      border: 1px solid var(--border);
      padding: 1rem;
      border-radius: 10px;
      overflow-x: auto;
      font-size: 0.82rem;
      max-height: 420px;
    }
  </style>
</head>
<body>

  <!-- Background 3D Particle Network Canvas -->
  <canvas id="bg-3d-canvas"></canvas>

  <div class="app-shell">
    <header>
      <div class="brand-wrap">
        <div class="cube-scene" title="3D Medical Core">
          <div class="cube">
            <div class="cube-face front">🏥</div>
            <div class="cube-face back">🧬</div>
            <div class="cube-face right">📊</div>
            <div class="cube-face left">💓</div>
            <div class="cube-face top">➕</div>
            <div class="cube-face bottom">🔬</div>
          </div>
        </div>
        <div>
          <h1>Hospital Patient Data Analysis System</h1>
          <div class="subtitle">3D Interactive Command Center • Full CRUD + Pandas/NumPy + Multi-Laptop LAN Server</div>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn btn-outline" onclick="toggleTheme()" id="theme-btn">☀️ Light / 🌙 Dark</button>
        <button class="btn btn-warning" onclick="switchTab('network')">🌐 Connect Laptops</button>
        <button class="btn btn-success" onclick="switchTab('visits'); document.getElementById('v_date').focus();">+ Add Visit</button>
        <button class="btn btn-accent" onclick="switchTab('patients');">+ Add Patient</button>
        <button class="btn btn-primary" onclick="refreshEverything()">🔄 Sync Live</button>
      </div>
    </header>

    <div class="disclaimer-bar">
      <span>⚠️ <b>OPERATIONAL STATISTICS ONLY:</b> Synthetic / de-identified records. Not clinical advice, diagnosis, or treatment recommendations.</span>
      <span style="font-weight:700;color:#34d399;">● 3D Engine & Multi-Laptop LAN Server Online ({{ primary_lan_url }})</span>
    </div>

    <!-- =================================================================== -->
    <!-- INTERACTIVE 3D HOLOGRAPHIC STAGE WITH 4 DIFFERENT 3D ANIMATIONS     -->
    <!-- =================================================================== -->
    <div class="hero-3d-wrapper">
      <div class="hero-3d-stage">
        <div class="hero-3d-info">
          <div>
            <div class="hero-badge">🧊 Real-Time 3D WebGL/Canvas Projection Engine</div>
            <h2 id="scene-title">1. 3D Bio-Medical DNA Double Helix</h2>
            <p id="scene-desc">
              Interactive 3D visualization powered by live hospital operational metrics. Switch between 4 distinct 3D animations below or drag the 3D scene with your mouse to rotate in 360° space.
            </p>
          </div>
          <div>
            <div style="font-size:0.74rem;text-transform:uppercase;letter-spacing:0.05em;color:#94a3b8;margin-bottom:0.45rem;font-weight:700;">
              Select 3D Animation Mode (4 Built-in 3D Scenes):
            </div>
            <div class="mode-switcher">
              <button class="mode-btn active" data-mode="dna" onclick="set3DMode('dna')">🧬 1. 3D DNA Helix</button>
              <button class="mode-btn" data-mode="towers" onclick="set3DMode('towers')">🏙️ 2. 3D Dept Towers</button>
              <button class="mode-btn" data-mode="sphere" onclick="set3DMode('sphere')">🌐 3. 3D Neural Sphere</button>
              <button class="mode-btn" data-mode="ecg" onclick="set3DMode('ecg')">💓 4. 3D ECG Wave Grid</button>
            </div>
          </div>
        </div>
        <div class="hero-canvas-box" id="hero-canvas-container">
          <canvas id="hero-3d-canvas"></canvas>
          <div class="canvas-hint">🖱️ Drag to Rotate 3D • Scroll to Zoom</div>
        </div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <nav class="nav-tabs">
      <button class="nav-tab active" data-tab="overview" onclick="switchTab('overview')">📊 Dashboard & Overview</button>
      <button class="nav-tab" data-tab="visits" onclick="switchTab('visits')">🗓️ Visits (Add / Edit / Filter)</button>
      <button class="nav-tab" data-tab="patients" onclick="switchTab('patients')">👥 Patients (Add / Edit)</button>
      <button class="nav-tab" data-tab="departments" onclick="switchTab('departments')">🏢 Departments (Add / Edit)</button>
      <button class="nav-tab" data-tab="charts" onclick="switchTab('charts')">📈 Matplotlib Charts (6)</button>
      <button class="nav-tab" data-tab="network" onclick="switchTab('network')">🌐 Share on LAN / Wi-Fi</button>
      <button class="nav-tab" data-tab="api" onclick="switchTab('api')">🔌 Backend API Console</button>
    </nav>

    <div class="container">

      <!-- 3D TILT KPI SUMMARY CARDS -->
      <div class="kpi-grid">
        <div class="kpi-card tilt-card">
          <div class="kpi-icon">🗓️</div>
          <div class="label">Total Visits</div>
          <div class="value" id="kpi-visits">{{ total_visits }}</div>
          <div class="sub" id="kpi-visits-sub">All recorded hospital visits</div>
        </div>
        <div class="kpi-card tilt-card">
          <div class="kpi-icon">👥</div>
          <div class="label">Registered Patients</div>
          <div class="value" id="kpi-patients">{{ total_patients }}</div>
          <div class="sub" id="kpi-unique-sub">De-identified profiles</div>
        </div>
        <div class="kpi-card tilt-card">
          <div class="kpi-icon">🏢</div>
          <div class="label">Active Departments</div>
          <div class="value" id="kpi-depts">{{ total_depts }}</div>
          <div class="sub">Hospital units tracked in 3D</div>
        </div>
        <div class="kpi-card tilt-card">
          <div class="kpi-icon">📈</div>
          <div class="label">Monthly Mean ± Std</div>
          <div class="value" id="kpi-monthly">{{ avg_monthly }}</div>
          <div class="sub" id="kpi-monthly-std">NumPy monthly traffic stats</div>
        </div>
        <div class="kpi-card tilt-card">
          <div class="kpi-icon">🚨</div>
          <div class="label">Emergency Share</div>
          <div class="value" id="kpi-emergency">--</div>
          <div class="sub" id="kpi-trend">Linear trend: calculating...</div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 1: DASHBOARD & OVERVIEW                                         -->
      <!-- =================================================================== -->
      <div id="tab-overview" class="tab-pane active">

        <!-- Quick Data Entry Bar right on the Dashboard -->
        <div class="card">
          <div class="card-header">
            <h2>⚡ Quick Data Entry — Record a New Visit Instantly</h2>
            <span style="font-size:0.8rem;color:var(--muted);">Updates KPIs, 3D Department Towers, and SQLite DB in real time</span>
          </div>
          <form onsubmit="submitQuickVisit(event)" class="form-grid">
            <div class="form-group">
              <label>Patient *</label>
              <select id="qv_patient" required></select>
            </div>
            <div class="form-group">
              <label>Department *</label>
              <select id="qv_dept" required></select>
            </div>
            <div class="form-group">
              <label>Visit Date *</label>
              <input type="date" id="qv_date" required>
            </div>
            <div class="form-group">
              <label>Visit Type *</label>
              <select id="qv_type" required>
                <option value="Outpatient">Outpatient</option>
                <option value="Inpatient">Inpatient</option>
                <option value="Emergency">Emergency</option>
                <option value="Follow-up">Follow-up</option>
                <option value="Teleconsult">Teleconsult</option>
              </select>
            </div>
            <div class="form-group">
              <label>Notes</label>
              <input type="text" id="qv_notes" placeholder="Optional visit notes...">
            </div>
            <div class="form-group">
              <button type="submit" class="btn btn-success" style="width:100%;justify-content:center;">➕ Save Visit</button>
            </div>
          </form>
        </div>

        <div class="two-col">
          <!-- Department Workload Table with Z-Scores -->
          <div class="card">
            <div class="card-header">
              <h2>🏢 Department Workload & NumPy Z-Scores</h2>
              <div style="display:flex;gap:0.4rem;">
                <button class="btn btn-outline btn-sm" onclick="set3DMode('towers')">🧊 View in 3D</button>
                <button class="btn btn-outline btn-sm" onclick="switchTab('departments')">Manage Depts →</button>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Department</th>
                    <th>Visits</th>
                    <th>Share</th>
                    <th>Unique Pts</th>
                    <th>Emergency</th>
                    <th>Z-Score</th>
                  </tr>
                </thead>
                <tbody id="overview-dept-tbody"></tbody>
              </table>
            </div>
          </div>

          <!-- Monthly Trends & MoM % Change -->
          <div class="card">
            <div class="card-header">
              <h2>📅 Monthly Visit Trends & MoM % Change</h2>
              <span id="trend-badge" class="badge badge-Outpatient">Trend</span>
            </div>
            <div class="table-wrap" style="max-height:380px;overflow-y:auto;">
              <table>
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Total Visits</th>
                    <th>MoM Change (%)</th>
                  </tr>
                </thead>
                <tbody id="overview-monthly-tbody"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="two-col">
          <!-- Age-Band Distribution -->
          <div class="card">
            <div class="card-header">
              <h2>👥 Age-Band Distribution</h2>
              <button class="btn btn-outline btn-sm" onclick="switchTab('patients')">Manage Patients →</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Age Band</th>
                    <th>Registered Patients</th>
                    <th>Total Visits</th>
                    <th>Share (%)</th>
                  </tr>
                </thead>
                <tbody id="overview-age-tbody"></tbody>
              </table>
            </div>
          </div>

          <!-- Visit Type Distribution -->
          <div class="card">
            <div class="card-header">
              <h2>🏥 Visit Type Breakdown</h2>
              <button class="btn btn-outline btn-sm" onclick="switchTab('visits')">Manage Visits →</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Visit Type</th>
                    <th>Total Visits</th>
                    <th>Share (%)</th>
                  </tr>
                </thead>
                <tbody id="overview-vtype-tbody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 2: VISITS MANAGEMENT (ADD / EDIT / DELETE / FILTER)             -->
      <!-- =================================================================== -->
      <div id="tab-visits" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>➕ Record New Patient Visit</h2>
            <span style="font-size:0.82rem;color:var(--muted);">POST /api/visits/</span>
          </div>
          <form onsubmit="createVisit(event)" class="form-grid">
            <div class="form-group">
              <label>Patient *</label>
              <select id="v_patient" required></select>
            </div>
            <div class="form-group">
              <label>Department *</label>
              <select id="v_dept" required></select>
            </div>
            <div class="form-group">
              <label>Visit Date (YYYY-MM-DD) *</label>
              <input type="date" id="v_date" required>
            </div>
            <div class="form-group">
              <label>Visit Type *</label>
              <select id="v_type" required>
                <option value="Outpatient">Outpatient</option>
                <option value="Inpatient">Inpatient</option>
                <option value="Emergency">Emergency</option>
                <option value="Follow-up">Follow-up</option>
                <option value="Teleconsult">Teleconsult</option>
              </select>
            </div>
            <div class="form-group">
              <label>Clinical / Operational Notes</label>
              <input type="text" id="v_notes" placeholder="e.g. Routine follow-up">
            </div>
            <div class="form-group">
              <button type="submit" class="btn btn-success" style="width:100%;justify-content:center;">➕ Add Visit</button>
            </div>
          </form>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>🔍 Filter & Edit Visits</h2>
            <div style="display:flex;gap:0.5rem;">
              <button class="btn btn-outline btn-sm" onclick="resetVisitFilters()">Reset Filters</button>
            </div>
          </div>

          <div class="form-grid" style="margin-bottom:1.2rem;padding:1rem;border-radius:10px;border:1px solid var(--border);">
            <div class="form-group">
              <label>Filter by Department</label>
              <select id="vf_dept" onchange="loadVisits()">
                <option value="">All Departments</option>
              </select>
            </div>
            <div class="form-group">
              <label>Filter by Visit Type</label>
              <select id="vf_type" onchange="loadVisits()">
                <option value="">All Visit Types</option>
                <option value="Outpatient">Outpatient</option>
                <option value="Inpatient">Inpatient</option>
                <option value="Emergency">Emergency</option>
                <option value="Follow-up">Follow-up</option>
                <option value="Teleconsult">Teleconsult</option>
              </select>
            </div>
            <div class="form-group">
              <label>From Date</label>
              <input type="date" id="vf_from" onchange="loadVisits()">
            </div>
            <div class="form-group">
              <label>To Date</label>
              <input type="date" id="vf_to" onchange="loadVisits()">
            </div>
            <div class="form-group">
              <label>Max Rows</label>
              <select id="vf_limit" onchange="loadVisits()">
                <option value="50">50 rows</option>
                <option value="100">100 rows</option>
                <option value="250">250 rows</option>
                <option value="500">All (up to 500)</option>
              </select>
            </div>
          </div>

          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Date</th>
                  <th>Patient</th>
                  <th>Department</th>
                  <th>Visit Type</th>
                  <th>Notes</th>
                  <th>Actions (Edit / Delete)</th>
                </tr>
              </thead>
              <tbody id="visits-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 3: PATIENTS MANAGEMENT (ADD / EDIT / DELETE)                    -->
      <!-- =================================================================== -->
      <div id="tab-patients" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>➕ Register New Patient (De-identified)</h2>
            <span style="font-size:0.82rem;color:var(--muted);">POST /api/patients/</span>
          </div>
          <form onsubmit="createPatient(event)" class="form-grid">
            <div class="form-group">
              <label>Age Band *</label>
              <select id="p_age_band" required>
                <option value="0-17">0-17</option>
                <option value="18-34" selected>18-34</option>
                <option value="35-49">35-49</option>
                <option value="50-64">50-64</option>
                <option value="65+">65+</option>
              </select>
            </div>
            <div class="form-group">
              <label>Gender *</label>
              <select id="p_gender" required>
                <option value="M">M</option>
                <option value="F">F</option>
                <option value="Other">Other</option>
                <option value="Prefer not to say">Prefer not to say</option>
              </select>
            </div>
            <div class="form-group">
              <button type="submit" class="btn btn-success">➕ Add Patient Record</button>
            </div>
          </form>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>👥 Registered Patients Directory</h2>
            <div style="display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;">
              <select id="pf_age" onchange="loadPatients()">
                <option value="">All Age Bands</option>
                <option value="0-17">0-17</option>
                <option value="18-34">18-34</option>
                <option value="35-49">35-49</option>
                <option value="50-64">50-64</option>
                <option value="65+">65+</option>
              </select>
              <select id="pf_gender" onchange="loadPatients()">
                <option value="">All Genders</option>
                <option value="M">M</option>
                <option value="F">F</option>
                <option value="Other">Other</option>
                <option value="Prefer not to say">Prefer not to say</option>
              </select>
              <select id="pf_limit" onchange="loadPatients()">
                <option value="50">50 rows</option>
                <option value="100">100 rows</option>
                <option value="300">All (up to 300)</option>
              </select>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Patient ID</th>
                  <th>Age Band</th>
                  <th>Gender</th>
                  <th>Total Visits</th>
                  <th>Created At</th>
                  <th>Actions (Edit / Delete)</th>
                </tr>
              </thead>
              <tbody id="patients-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 4: DEPARTMENTS MANAGEMENT (ADD / EDIT / DELETE)                 -->
      <!-- =================================================================== -->
      <div id="tab-departments" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>➕ Add New Hospital Department</h2>
            <span style="font-size:0.82rem;color:var(--muted);">POST /api/departments/</span>
          </div>
          <form onsubmit="createDepartment(event)" class="form-grid">
            <div class="form-group">
              <label>Department Name *</label>
              <input type="text" id="d_name" placeholder="e.g. Radiology" required>
            </div>
            <div class="form-group">
              <label>Description</label>
              <input type="text" id="d_desc" placeholder="e.g. Diagnostic imaging and X-ray services">
            </div>
            <div class="form-group">
              <button type="submit" class="btn btn-success">➕ Create Department</button>
            </div>
          </form>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>🏢 Hospital Departments & Workload</h2>
            <span style="font-size:0.82rem;color:var(--muted);">Click Edit to modify name/description or Delete to remove unused departments</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Department Name</th>
                  <th>Description</th>
                  <th>Total Visits</th>
                  <th>Unique Patients</th>
                  <th>Emergencies</th>
                  <th>Actions (Edit / Delete)</th>
                </tr>
              </thead>
              <tbody id="departments-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 5: MATPLOTLIB CHARTS GALLERY (6 CHARTS)                         -->
      <!-- =================================================================== -->
      <div id="tab-charts" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>📊 Operational Analytics Charts (Matplotlib)</h2>
            <div style="display:flex;gap:0.6rem;align-items:center;">
              <span id="chart-status" style="font-size:0.85rem;font-weight:600;color:var(--success);"></span>
              <button class="btn btn-primary" onclick="generateAndShowCharts()">🔄 Regenerate All 6 Charts</button>
            </div>
          </div>
          <div class="charts-grid" id="charts-gallery">
            <div class="chart-box"><img id="img-c1" src="/charts/dept_workload_bar.png" alt="Department Workload"></div>
            <div class="chart-box"><img id="img-c2" src="/charts/monthly_visits_line.png" alt="Monthly Visits Trend"></div>
            <div class="chart-box"><img id="img-c3" src="/charts/visit_type_pie.png" alt="Visit Type Pie"></div>
            <div class="chart-box"><img id="img-c4" src="/charts/age_band_bar.png" alt="Age Band Bar"></div>
            <div class="chart-box"><img id="img-c5" src="/charts/dept_emergency_heatmap.png" alt="Emergency vs Total"></div>
            <div class="chart-box"><img id="img-c6" src="/charts/day_of_week_bar.png" alt="Day of Week Volume"></div>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB: SHARE ON NETWORK / CONNECT OTHER LAPTOPS                       -->
      <!-- =================================================================== -->
      <div id="tab-network" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>🌐 Run on Anyone's Laptop Using Your Device as the Local Server</h2>
            <span class="badge badge-Outpatient">Multi-Device LAN / Wi-Fi / Hotspot Ready</span>
          </div>
          <p style="margin-top:0;color:var(--muted);font-size:0.92rem;line-height:1.5;">
            Your laptop is hosting the live 3D website and SQLite database on all network interfaces (<code>0.0.0.0:{{ server_port }}</code>).
            Anyone connected to the <b>same Wi-Fi network, LAN, or your phone/laptop Mobile Hotspot</b> can open the link below in their browser to view, add, and edit data in real time:
          </p>

          <div style="background:rgba(56,189,248,0.08);border:2px dashed var(--primary);border-radius:12px;padding:1.25rem;margin-bottom:1.25rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
            <div>
              <div style="font-size:0.78rem;font-weight:700;color:var(--muted);text-transform:uppercase;">Shareable URL for Other Laptops & Phones</div>
              <div id="lan-primary-url" style="font-size:1.5rem;font-weight:800;color:var(--primary);font-family:monospace;margin-top:0.25rem;">{{ primary_lan_url }}</div>
              <div id="lan-all-urls" style="font-size:0.82rem;color:var(--muted);margin-top:0.25rem;">Host: <b>{{ hostname }}</b> | All detected IPs: {{ all_lan_ips }}</div>
            </div>
            <div style="display:flex;gap:0.6rem;">
              <button class="btn btn-primary" onclick="copyLanUrl()">📋 Copy Share Link</button>
            </div>
          </div>

          <div class="two-col">
            <div style="padding:1.1rem;border-radius:10px;border:1px solid var(--border);">
              <h3 style="margin-top:0;font-size:0.98rem;color:var(--primary);">✅ Step-by-Step for Other Laptops</h3>
              <ol style="margin:0;padding-left:1.2rem;font-size:0.88rem;line-height:1.65;color:var(--text);">
                <li>Connect your laptop and the other person's laptop to the <b>same Wi-Fi</b> (or turn on your laptop/phone <b>Mobile Hotspot</b> and connect them to it).</li>
                <li>Keep <code>py app.py</code> running on your laptop.</li>
                <li>On the other person's laptop, open Chrome/Edge/Safari and type: <br><code style="color:var(--primary);font-weight:bold;">{{ primary_lan_url }}</code></li>
                <li>Every visit, patient, or department they add or edit updates your database and 3D visuals immediately!</li>
              </ol>
            </div>

            <div style="padding:1.1rem;border-radius:10px;border:1px solid rgba(245,158,11,0.35);">
              <h3 style="margin-top:0;font-size:0.98rem;color:#fbbf24;">🛡️ Troubleshooting: If Other Laptops Cannot Connect</h3>
              <p style="margin:0 0 0.6rem;font-size:0.85rem;color:var(--muted);line-height:1.5;">
                Sometimes <b>Windows Defender Firewall</b> blocks incoming connections on port <code>{{ server_port }}</code>. Run this command once in <b>Command Prompt / PowerShell (Run as Administrator)</b> on your laptop:
              </p>
              <pre style="background:#050811;color:#38bdf8;padding:0.65rem;border-radius:6px;font-size:0.78rem;overflow-x:auto;margin:0;">netsh advfirewall firewall add rule name="Hospital Analytics Port {{ server_port }}" dir=in action=allow protocol=TCP localport={{ server_port }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- =================================================================== -->
      <!-- TAB 6: INTERACTIVE BACKEND API TESTER                               -->
      <!-- =================================================================== -->
      <div id="tab-api" class="tab-pane">
        <div class="card">
          <div class="card-header">
            <h2>🔌 Interactive REST API Explorer & Tester</h2>
            <span style="font-size:0.82rem;color:var(--muted);">Test any GET / POST / PUT / DELETE route live against the Flask backend</span>
          </div>
          <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:1rem;">
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/health')">GET /health</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/network-info')">GET /api/network-info</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/analysis/summary')">GET /api/analysis/summary</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/analysis/department-workload')">GET /api/analysis/department-workload</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/analysis/monthly-trends')">GET /api/analysis/monthly-trends</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/analysis/age-band')">GET /api/analysis/age-band</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/departments/')">GET /api/departments/</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/patients/?limit=10')">GET /api/patients/?limit=10</button>
            <button class="btn btn-outline btn-sm" onclick="quickApi('GET', '/api/visits/?limit=10')">GET /api/visits/?limit=10</button>
          </div>

          <div class="form-grid" style="margin-bottom:1rem;">
            <div class="form-group">
              <label>HTTP Method</label>
              <select id="api_method">
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="DELETE">DELETE</option>
              </select>
            </div>
            <div class="form-group" style="grid-column: span 2;">
              <label>Endpoint URL</label>
              <input type="text" id="api_url" value="/api/analysis/summary">
            </div>
            <div class="form-group">
              <button class="btn btn-primary" onclick="sendCustomApi()">🚀 Send Request</button>
            </div>
          </div>
          <div class="form-group" style="margin-bottom:1rem;">
            <label>JSON Body (for POST / PUT requests)</label>
            <textarea id="api_body" rows="3" placeholder='{"age_band": "18-34", "gender": "F"}'></textarea>
          </div>
          <pre class="json-box" id="api_response">Click any endpoint button above or hit "Send Request" to inspect the live JSON response...</pre>
        </div>
      </div>

    </div>
  </div>

  <!-- ===================================================================== -->
  <!-- EDIT MODAL (Supports Editing Visits, Patients, and Departments)       -->
  <!-- ===================================================================== -->
  <div class="modal-backdrop" id="edit-modal">
    <div class="modal">
      <div class="modal-header">
        <h3 id="modal-title">Edit Record</h3>
        <button class="btn btn-outline btn-sm" onclick="closeModal()">✕</button>
      </div>
      <form id="modal-form" onsubmit="submitModalEdit(event)">
        <div id="modal-fields" style="display:flex;flex-direction:column;gap:0.85rem;"></div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
          <button type="submit" class="btn btn-primary">💾 Save Changes</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Toast Notification -->
  <div id="toast"></div>

  <script>
    // =========================================================================
    // GLOBAL STATE & THEME SWITCHER
    // =========================================================================
    let cachedDepartments = [];
    let cachedPatients = [];
    let cachedVisits = [];
    let currentEdit = { type: null, id: null };

    const todayStr = new Date().toISOString().split('T')[0];
    document.getElementById('qv_date').value = todayStr;
    document.getElementById('v_date').value = todayStr;

    function toggleTheme() {
      const root = document.documentElement;
      const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      showToast(`Switched to ${next.toUpperCase()} 3D theme`);
    }

    function showToast(msg, kind = 'success') {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.className = 'show ' + kind;
      setTimeout(() => { t.className = ''; }, 3200);
    }

    function switchTab(tabId) {
      document.querySelectorAll('.nav-tab').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
      });
      document.querySelectorAll('.tab-pane').forEach(p => {
        p.classList.toggle('active', p.id === 'tab-' + tabId);
      });
      if (tabId === 'charts') {
        refreshChartImages();
      }
    }

    // =========================================================================
    // 3D INTERACTIVE CARD TILT EFFECT (Holographic Perspective on Hover)
    // =========================================================================
    document.querySelectorAll('.tilt-card').forEach(card => {
      card.addEventListener('mousemove', e => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const rotY = ((x / rect.width) - 0.5) * 18;
        const rotX = ((0.5 - (y / rect.height))) * 18;
        card.style.transform = `perspective(800px) rotateX(${rotX}deg) rotateY(${rotY}deg) translateZ(6px)`;
      });
      card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(800px) rotateX(0deg) rotateY(0deg) translateZ(0)';
      });
    });

    // =========================================================================
    // AMBIENT 3D BACKGROUND PARTICLE NETWORK
    // =========================================================================
    (function initAmbientBg3D() {
      const canvas = document.getElementById('bg-3d-canvas');
      const ctx = canvas.getContext('2d');
      let w = canvas.width = window.innerWidth;
      let h = canvas.height = window.innerHeight;
      window.addEventListener('resize', () => {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
      });

      const nodes = Array.from({ length: 48 }, () => ({
        x: (Math.random() - 0.5) * 1200,
        y: (Math.random() - 0.5) * 800,
        z: Math.random() * 800 + 100,
        vx: (Math.random() - 0.5) * 0.6,
        vy: (Math.random() - 0.5) * 0.6,
        vz: (Math.random() - 0.5) * 1.1
      }));

      function renderBg() {
        ctx.clearRect(0, 0, w, h);
        const fov = 450;
        const projected = [];

        for (const n of nodes) {
          n.x += n.vx; n.y += n.vy; n.z += n.vz;
          if (n.z < 80) n.z = 850;
          if (n.z > 880) n.z = 90;
          if (Math.abs(n.x) > 700) n.vx *= -1;
          if (Math.abs(n.y) > 500) n.vy *= -1;

          const scale = fov / (fov + n.z);
          const px = w / 2 + n.x * scale;
          const py = h / 2 + n.y * scale;
          projected.push({ px, py, scale, z: n.z });
        }

        for (let i = 0; i < projected.length; i++) {
          const a = projected[i];
          ctx.beginPath();
          ctx.arc(a.px, a.py, Math.max(1.2, 3.5 * a.scale), 0, Math.PI * 2);
          ctx.fillStyle = `rgba(56, 189, 248, ${a.scale * 0.8})`;
          ctx.fill();

          for (let j = i + 1; j < projected.length; j++) {
            const b = projected[j];
            const dist = Math.hypot(a.px - b.px, a.py - b.py);
            if (dist < 135) {
              ctx.beginPath();
              ctx.moveTo(a.px, a.py);
              ctx.lineTo(b.px, b.py);
              ctx.strokeStyle = `rgba(45, 212, 191, ${(1 - dist / 135) * 0.25})`;
              ctx.lineWidth = 1;
              ctx.stroke();
            }
          }
        }
        requestAnimationFrame(renderBg);
      }
      renderBg();
    })();

    // =========================================================================
    // HERO 3D ENGINE — 4 DIFFERENT INTERACTIVE 3D ANIMATIONS
    //   Mode 1: 'dna'    — 3D Bio-Medical DNA Double Helix
    //   Mode 2: 'towers' — 3D Live Department Workload Towers
    //   Mode 3: 'sphere' — 3D Hospital Neural Network Geodesic Sphere
    //   Mode 4: 'ecg'    — 3D Holographic ECG Vital Wave Terrain
    // =========================================================================
    let current3DMode = 'dna';
    const sceneMeta = {
      dna: {
        title: '1. 3D Bio-Medical DNA Double Helix',
        desc: 'Real-time 3D double helix with depth-sorted molecular base pairs and glowing clinical telemetry particles. Drag with your mouse to orbit in 3D.'
      },
      towers: {
        title: '2. 3D Live Department Workload Towers',
        desc: 'Interactive 3D extruded bar towers dynamically scaled from your live SQLite department visit counts and emergency rates.'
      },
      sphere: {
        title: '3. 3D Hospital Neural Network Sphere',
        desc: '3D geodesic sphere connecting patient cohorts and hospital departments with animated diagnostic signal pulses.'
      },
      ecg: {
        title: '4. 3D Holographic ECG & Vital Wave Terrain',
        desc: '3D perspective surface wave with real-time cardiac QRS-complex heartbeat peaks sweeping across a holographic grid.'
      }
    };

    function set3DMode(mode) {
      current3DMode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.getAttribute('data-mode') === mode);
      });
      if (sceneMeta[mode]) {
        document.getElementById('scene-title').textContent = sceneMeta[mode].title;
        document.getElementById('scene-desc').textContent = sceneMeta[mode].desc;
      }
    }

    (function initHero3DEngine() {
      const container = document.getElementById('hero-canvas-container');
      const canvas = document.getElementById('hero-3d-canvas');
      const ctx = canvas.getContext('2d');

      let width = 600, height = 270;
      function resizeHero() {
        const r = container.getBoundingClientRect();
        width = canvas.width = Math.max(300, r.width);
        height = canvas.height = Math.max(250, r.height);
      }
      window.addEventListener('resize', resizeHero);
      setTimeout(resizeHero, 50);

      // Camera & Mouse Orbit State
      let rotY = 0.4, rotX = 0.28, zoom = 1.0;
      let isDragging = false, lastX = 0, lastY = 0;

      canvas.addEventListener('mousedown', e => {
        isDragging = true; lastX = e.clientX; lastY = e.clientY;
      });
      window.addEventListener('mousemove', e => {
        if (!isDragging) return;
        rotY += (e.clientX - lastX) * 0.009;
        rotX = Math.max(-1.1, Math.min(1.1, rotX + (e.clientY - lastY) * 0.009));
        lastX = e.clientX; lastY = e.clientY;
      });
      window.addEventListener('mouseup', () => { isDragging = false; });
      canvas.addEventListener('wheel', e => {
        e.preventDefault();
        zoom = Math.max(0.65, Math.min(1.6, zoom - e.deltaY * 0.001));
      }, { passive: false });

      // 3D Point Projection Helper
      function project3D(x, y, z) {
        // Rotate around Y
        const cosY = Math.cos(rotY), sinY = Math.sin(rotY);
        const x1 = x * cosY - z * sinY;
        const z1 = z * cosY + x * sinY;
        // Rotate around X
        const cosX = Math.cos(rotX), sinX = Math.sin(rotX);
        const y2 = y * cosX - z1 * sinX;
        const z2 = z1 * cosX + y * sinX;

        const fov = 420 * zoom;
        const dist = 460;
        const scale = fov / Math.max(60, dist + z2);
        return {
          x: width / 2 + x1 * scale,
          y: height / 2 + y2 * scale,
          z: z2,
          scale
        };
      }

      // Precompute Sphere points for Mode 3
      const spherePts = [];
      const N_SPHERE = 64;
      for (let i = 0; i < N_SPHERE; i++) {
        const phi = Math.acos(1 - 2 * (i + 0.5) / N_SPHERE);
        const theta = Math.PI * (1 + Math.sqrt(5)) * i;
        const r = 115;
        spherePts.push({
          x: r * Math.cos(theta) * Math.sin(phi),
          y: r * Math.sin(theta) * Math.sin(phi),
          z: r * Math.cos(phi),
          hue: (i * 5) % 360
        });
      }

      let t = 0;
      function animateHero3D() {
        t += 0.025;
        if (!isDragging) {
          rotY += 0.0075;
        }
        ctx.clearRect(0, 0, width, height);

        if (current3DMode === 'dna') {
          // MODE 1: 3D DNA DOUBLE HELIX
          const items = [];
          const numRungs = 26;
          for (let i = 0; i < numRungs; i++) {
            const xPos = (i - numRungs / 2) * 14;
            const angle = i * 0.42 + t * 1.4;
            const r = 68;
            const y1 = Math.cos(angle) * r;
            const z1 = Math.sin(angle) * r;
            const y2 = Math.cos(angle + Math.PI) * r;
            const z2 = Math.sin(angle + Math.PI) * r;

            const p1 = project3D(xPos, y1, z1);
            const p2 = project3D(xPos, y2, z2);
            items.push({ type: 'rung', p1, p2, z: (p1.z + p2.z) / 2 });
            items.push({ type: 'node', p: p1, color: '#38bdf8', z: p1.z, r: 6.5 });
            items.push({ type: 'node', p: p2, color: '#2dd4bf', z: p2.z, r: 6.5 });
          }
          items.sort((a, b) => b.z - a.z);

          for (const it of items) {
            if (it.type === 'rung') {
              ctx.beginPath();
              ctx.moveTo(it.p1.x, it.p1.y);
              ctx.lineTo(it.p2.x, it.p2.y);
              ctx.strokeStyle = 'rgba(168, 85, 247, 0.48)';
              ctx.lineWidth = Math.max(1, 2.2 * it.p1.scale);
              ctx.stroke();
            } else {
              const rad = Math.max(2, it.r * it.p.scale);
              const grad = ctx.createRadialGradient(it.p.x - rad*0.3, it.p.y - rad*0.3, 1, it.p.x, it.p.y, rad);
              grad.addColorStop(0, '#ffffff');
              grad.addColorStop(0.4, it.color);
              grad.addColorStop(1, 'rgba(2, 132, 199, 0.15)');
              ctx.beginPath();
              ctx.arc(it.p.x, it.p.y, rad, 0, Math.PI * 2);
              ctx.fillStyle = grad;
              ctx.fill();
            }
          }
        } else if (current3DMode === 'towers') {
          // MODE 2: 3D LIVE DEPARTMENT WORKLOAD TOWERS
          const depts = cachedDepartments.length ? cachedDepartments.slice(0, 8) : [
            { department_name: 'Cardiology', total_visits: 35, emergency_visits: 8 },
            { department_name: 'Emergency', total_visits: 32, emergency_visits: 18 },
            { department_name: 'Neurology', total_visits: 28, emergency_visits: 5 },
            { department_name: 'Pediatrics', total_visits: 30, emergency_visits: 4 },
            { department_name: 'Orthopedics', total_visits: 26, emergency_visits: 6 },
            { department_name: 'Oncology', total_visits: 24, emergency_visits: 3 }
          ];
          const maxV = Math.max(...depts.map(d => d.total_visits || 1), 10);
          const cols = ['#38bdf8', '#2dd4bf', '#a855f7', '#f59e0b', '#10b981', '#ec4899', '#6366f1', '#14b8a6'];

          // Draw 3D Floor Grid
          ctx.strokeStyle = 'rgba(56, 189, 248, 0.18)';
          ctx.lineWidth = 1;
          for (let gx = -160; gx <= 160; gx += 40) {
            const a = project3D(gx, 75, -100);
            const b = project3D(gx, 75, 100);
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
          for (let gz = -100; gz <= 100; gz += 40) {
            const a = project3D(-160, 75, gz);
            const b = project3D(160, 75, gz);
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }

          // Build 3D Pillars
          const pillars = depts.map((d, idx) => {
            const x = (idx - (depts.length - 1) / 2) * 38;
            const z = (idx % 2 === 0) ? -22 : 22;
            const hBar = Math.max(18, ((d.total_visits || 1) / maxV) * 135) * (0.92 + 0.08 * Math.sin(t * 2 + idx));
            const base = project3D(x, 75, z);
            const top = project3D(x, 75 - hBar, z);
            return { d, idx, base, top, z: base.z, color: cols[idx % cols.length] };
          }).sort((a, b) => b.z - a.z);

          for (const p of pillars) {
            const wBar = Math.max(8, 18 * p.base.scale);
            // 3D Pillar Body
            const grad = ctx.createLinearGradient(p.top.x, p.top.y, p.base.x, p.base.y);
            grad.addColorStop(0, p.color);
            grad.addColorStop(1, 'rgba(15, 23, 42, 0.85)');
            ctx.fillStyle = grad;
            ctx.strokeStyle = '#e0f2fe';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(p.top.x - wBar / 2, p.top.y, wBar, Math.max(4, p.base.y - p.top.y), 4);
            ctx.fill();
            ctx.stroke();

            // Floating Value & Dept Label
            ctx.fillStyle = '#ffffff';
            ctx.font = `bold ${Math.round(11 * p.top.scale)}px Segoe UI, sans-serif`;
            ctx.textAlign = 'center';
            ctx.fillText(`${p.d.total_visits}`, p.top.x, p.top.y - 6);
            ctx.fillStyle = '#94a3b8';
            ctx.font = `${Math.round(9.5 * p.base.scale)}px Segoe UI, sans-serif`;
            ctx.fillText(p.d.department_name.slice(0, 8), p.base.x, p.base.y + 14);
          }
        } else if (current3DMode === 'sphere') {
          // MODE 3: 3D HOSPITAL NEURAL NETWORK SPHERE
          const proj = spherePts.map(pt => ({
            ...project3D(pt.x, pt.y, pt.z),
            hue: pt.hue
          }));

          for (let i = 0; i < proj.length; i++) {
            for (let j = i + 1; j < proj.length; j++) {
              const d = Math.hypot(proj[i].x - proj[j].x, proj[i].y - proj[j].y);
              if (d < 52) {
                ctx.beginPath();
                ctx.moveTo(proj[i].x, proj[i].y);
                ctx.lineTo(proj[j].x, proj[j].y);
                ctx.strokeStyle = `rgba(56, 189, 248, ${(1 - d / 52) * 0.42})`;
                ctx.lineWidth = 1;
                ctx.stroke();
              }
            }
          }
          proj.sort((a, b) => b.z - a.z);
          for (const p of proj) {
            const r = Math.max(1.8, 4.8 * p.scale);
            ctx.beginPath();
            ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
            ctx.fillStyle = `hsl(${(p.hue + t * 40) % 360}, 85%, 65%)`;
            ctx.fill();
          }
        } else if (current3DMode === 'ecg') {
          // MODE 4: 3D HOLOGRAPHIC ECG & VITAL WAVE TERRAIN
          const rows = 9, cols = 28;
          for (let r = 0; r < rows; r++) {
            ctx.beginPath();
            for (let c = 0; c < cols; c++) {
              const x = (c - cols / 2) * 14;
              const z = (r - rows / 2) * 22;
              const phase = (c * 0.35 - t * 2.4);
              const qrs = Math.exp(-Math.pow(((phase % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2) - 3.0, 2) * 18) * -68;
              const wave = Math.sin(phase) * 12 + Math.cos(r * 0.6 + t) * 8 + qrs;
              const pt = project3D(x, wave, z);
              if (c === 0) ctx.moveTo(pt.x, pt.y);
              else ctx.lineTo(pt.x, pt.y);
            }
            ctx.strokeStyle = r === Math.floor(rows / 2) ? '#34d399' : 'rgba(56, 189, 248, 0.45)';
            ctx.lineWidth = r === Math.floor(rows / 2) ? 2.6 : 1.2;
            ctx.stroke();
          }
        }

        requestAnimationFrame(animateHero3D);
      }
      animateHero3D();
    })();

    // =========================================================================
    // MASTER DATA LOADER
    // =========================================================================
    async function refreshEverything() {
      await Promise.all([
        loadDepartments(),
        loadPatients(),
        loadOverviewAnalytics()
      ]);
      await loadVisits();
    }

    async function loadOverviewAnalytics() {
      try {
        const [sumRes, deptRes, monRes, ageRes] = await Promise.all([
          fetch('/api/analysis/summary').then(r => r.json()),
          fetch('/api/analysis/department-workload').then(r => r.json()),
          fetch('/api/analysis/monthly-trends').then(r => r.json()),
          fetch('/api/analysis/age-band').then(r => r.json())
        ]);

        if (sumRes.status === 'success') {
          const d = sumRes.data;
          document.getElementById('kpi-visits').textContent = d.total_visits;
          document.getElementById('kpi-patients').textContent = d.total_registered_patients;
          document.getElementById('kpi-unique-sub').textContent = `${d.unique_patients_visited} with recorded visits`;
          document.getElementById('kpi-depts').textContent = d.total_departments;
          document.getElementById('kpi-monthly').textContent = d.monthly_stats.mean;
          document.getElementById('kpi-monthly-std').textContent = `Median: ${d.monthly_stats.median} | Std: ±${d.monthly_stats.std}`;
          document.getElementById('kpi-emergency').textContent = `${d.emergency_rate_pct}%`;

          const vtBody = document.getElementById('overview-vtype-tbody');
          const totalV = Math.max(d.total_visits, 1);
          vtBody.innerHTML = Object.entries(d.visit_type_breakdown).map(([vtype, count]) => {
            const pct = ((count / totalV) * 100).toFixed(1);
            return `<tr>
              <td><span class="badge badge-${vtype}">${vtype}</span></td>
              <td><b>${count}</b></td>
              <td>${pct}%</td>
            </tr>`;
          }).join('');
        }

        if (deptRes.status === 'success') {
          const tbody = document.getElementById('overview-dept-tbody');
          tbody.innerHTML = deptRes.data.departments.map(d => `
            <tr>
              <td><b>${d.department_name}</b></td>
              <td><b>${d.total_visits}</b></td>
              <td>${d.share_pct}%</td>
              <td>${d.unique_patients}</td>
              <td><span class="badge badge-Emergency">${d.emergency_visits}</span></td>
              <td><code>${d.z_score >= 0 ? '+' : ''}${d.z_score}</code></td>
            </tr>
          `).join('');
        }

        if (monRes.status === 'success') {
          const mData = monRes.data;
          document.getElementById('kpi-trend').textContent =
            `Trend: ${mData.trend_direction} (${mData.linear_slope >= 0 ? '+' : ''}${mData.linear_slope}/mo)`;
          const tb = document.getElementById('trend-badge');
          tb.textContent = `${mData.trend_direction} (${mData.linear_slope >= 0 ? '+' : ''}${mData.linear_slope}/mo)`;

          const mBody = document.getElementById('overview-monthly-tbody');
          mBody.innerHTML = mData.months.slice().reverse().map(m => {
            const mom = m.mom_change_pct === null ? '—' : `${m.mom_change_pct >= 0 ? '+' : ''}${m.mom_change_pct}%`;
            const color = m.mom_change_pct > 0 ? '#34d399' : (m.mom_change_pct < 0 ? '#f87171' : '#94a3b8');
            return `<tr>
              <td><b>${m.year_month}</b></td>
              <td>${m.total_visits}</td>
              <td style="color:${color};font-weight:700;">${mom}</td>
            </tr>`;
          }).join('');
        }

        if (ageRes.status === 'success') {
          const aBody = document.getElementById('overview-age-tbody');
          aBody.innerHTML = ageRes.data.map(a => `
            <tr>
              <td><b>${a.age_band}</b></td>
              <td>${a.registered_patients}</td>
              <td><b>${a.total_visits}</b></td>
              <td>${a.visit_share_pct}%</td>
            </tr>
          `).join('');
        }
      } catch (e) {
        console.error('Error loading overview:', e);
      }
    }

    // =========================================================================
    // DEPARTMENTS CRUD
    // =========================================================================
    async function loadDepartments() {
      const res = await fetch('/api/departments/').then(r => r.json());
      if (res.status !== 'success') return;
      cachedDepartments = res.data;

      const deptOpts = cachedDepartments.map(d =>
        `<option value="${d.department_id}">${d.department_name} (#${d.department_id})</option>`
      ).join('');
      document.getElementById('qv_dept').innerHTML = deptOpts;
      document.getElementById('v_dept').innerHTML = deptOpts;

      const filterVal = document.getElementById('vf_dept').value;
      document.getElementById('vf_dept').innerHTML = `<option value="">All Departments</option>` + deptOpts;
      document.getElementById('vf_dept').value = filterVal;

      const tbody = document.getElementById('departments-tbody');
      tbody.innerHTML = cachedDepartments.map(d => `
        <tr>
          <td>#${d.department_id}</td>
          <td><b>${d.department_name}</b></td>
          <td>${d.description || '<span style="color:#94a3b8;">—</span>'}</td>
          <td><b>${d.total_visits}</b></td>
          <td>${d.unique_patients}</td>
          <td><span class="badge badge-Emergency">${d.emergency_visits}</span></td>
          <td class="actions-cell">
            <button class="btn btn-outline btn-sm" onclick="openEditDepartment(${d.department_id})">✏️ Edit</button>
            <button class="btn btn-danger btn-sm" onclick="deleteDepartment(${d.department_id})">🗑️ Delete</button>
          </td>
        </tr>
      `).join('');
    }

    async function createDepartment(e) {
      e.preventDefault();
      const name = document.getElementById('d_name').value.trim();
      const desc = document.getElementById('d_desc').value.trim();
      const res = await fetch('/api/departments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ department_name: name, description: desc })
      }).then(r => r.json());

      if (res.status === 'success') {
        showToast(`Department "${name}" created!`);
        document.getElementById('d_name').value = '';
        document.getElementById('d_desc').value = '';
        await refreshEverything();
      } else {
        showToast(res.message || 'Failed to create department', 'error');
      }
    }

    function openEditDepartment(deptId) {
      const d = cachedDepartments.find(x => x.department_id === deptId);
      if (!d) return;
      currentEdit = { type: 'department', id: deptId };
      document.getElementById('modal-title').textContent = `Edit Department #${deptId}`;
      document.getElementById('modal-fields').innerHTML = `
        <div class="form-group">
          <label>Department Name *</label>
          <input type="text" id="edit_d_name" value="${d.department_name.replace(/"/g, '&quot;')}" required>
        </div>
        <div class="form-group">
          <label>Description</label>
          <input type="text" id="edit_d_desc" value="${(d.description || '').replace(/"/g, '&quot;')}">
        </div>
      `;
      document.getElementById('edit-modal').classList.add('open');
    }

    async function deleteDepartment(deptId) {
      const d = cachedDepartments.find(x => x.department_id === deptId);
      if (!confirm(`Delete department "${d ? d.department_name : deptId}"?`)) return;
      const res = await fetch(`/api/departments/${deptId}`, { method: 'DELETE' }).then(r => r.json());
      if (res.status === 'success') {
        showToast('Department deleted!');
        await refreshEverything();
      } else {
        showToast(res.message || 'Cannot delete department with existing visits', 'error');
      }
    }

    // =========================================================================
    // PATIENTS CRUD
    // =========================================================================
    async function loadPatients() {
      const age = document.getElementById('pf_age').value;
      const gender = document.getElementById('pf_gender').value;
      const limit = document.getElementById('pf_limit').value;

      const params = new URLSearchParams({ limit });
      if (age) params.append('age_band', age);
      if (gender) params.append('gender', gender);

      const res = await fetch(`/api/patients/?${params.toString()}`).then(r => r.json());
      if (res.status !== 'success') return;
      cachedPatients = res.data;

      const allPtsRes = await fetch('/api/patients/?limit=500').then(r => r.json());
      const allPts = allPtsRes.status === 'success' ? allPtsRes.data : cachedPatients;
      const ptOpts = allPts.map(p =>
        `<option value="${p.patient_id}">Patient #${p.patient_id} (${p.age_band}, ${p.gender})</option>`
      ).join('');
      document.getElementById('qv_patient').innerHTML = ptOpts;
      document.getElementById('v_patient').innerHTML = ptOpts;

      const tbody = document.getElementById('patients-tbody');
      tbody.innerHTML = cachedPatients.map(p => `
        <tr>
          <td><b>#${p.patient_id}</b></td>
          <td><span class="badge badge-Inpatient">${p.age_band}</span></td>
          <td>${p.gender}</td>
          <td><b>${p.visit_count || 0}</b> visits</td>
          <td style="color:var(--muted);font-size:0.8rem;">${p.created_at || '—'}</td>
          <td class="actions-cell">
            <button class="btn btn-outline btn-sm" onclick="openEditPatient(${p.patient_id})">✏️ Edit</button>
            <button class="btn btn-danger btn-sm" onclick="deletePatient(${p.patient_id})">🗑️ Delete</button>
          </td>
        </tr>
      `).join('');
    }

    async function createPatient(e) {
      e.preventDefault();
      const age_band = document.getElementById('p_age_band').value;
      const gender = document.getElementById('p_gender').value;
      const res = await fetch('/api/patients/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ age_band, gender })
      }).then(r => r.json());

      if (res.status === 'success') {
        showToast(`Patient #${res.data.patient_id} created (${age_band}, ${gender})!`);
        await refreshEverything();
      } else {
        showToast(res.message || 'Error creating patient', 'error');
      }
    }

    function openEditPatient(patientId) {
      const p = cachedPatients.find(x => x.patient_id === patientId);
      if (!p) return;
      currentEdit = { type: 'patient', id: patientId };
      document.getElementById('modal-title').textContent = `Edit Patient #${patientId}`;
      const bands = ['0-17', '18-34', '35-49', '50-64', '65+'];
      const genders = ['M', 'F', 'Other', 'Prefer not to say'];
      document.getElementById('modal-fields').innerHTML = `
        <div class="form-group">
          <label>Age Band *</label>
          <select id="edit_p_age" required>
            ${bands.map(b => `<option value="${b}" ${p.age_band === b ? 'selected' : ''}>${b}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label>Gender *</label>
          <select id="edit_p_gender" required>
            ${genders.map(g => `<option value="${g}" ${p.gender === g ? 'selected' : ''}>${g}</option>`).join('')}
          </select>
        </div>
      `;
      document.getElementById('edit-modal').classList.add('open');
    }

    async function deletePatient(patientId) {
      if (!confirm(`Delete Patient #${patientId}?`)) return;
      const res = await fetch(`/api/patients/${patientId}`, { method: 'DELETE' }).then(r => r.json());
      if (res.status === 'success') {
        showToast(`Patient #${patientId} deleted!`);
        await refreshEverything();
      } else {
        showToast(res.message || 'Cannot delete patient with existing visits', 'error');
      }
    }

    // =========================================================================
    // VISITS CRUD & FILTERING
    // =========================================================================
    async function loadVisits() {
      const dept_id = document.getElementById('vf_dept').value;
      const visit_type = document.getElementById('vf_type').value;
      const date_from = document.getElementById('vf_from').value;
      const date_to = document.getElementById('vf_to').value;
      const limit = document.getElementById('vf_limit').value;

      const params = new URLSearchParams({ limit });
      if (dept_id) params.append('dept_id', dept_id);
      if (visit_type) params.append('visit_type', visit_type);
      if (date_from) params.append('date_from', date_from);
      if (date_to) params.append('date_to', date_to);

      const res = await fetch(`/api/visits/?${params.toString()}`).then(r => r.json());
      if (res.status !== 'success') return;
      cachedVisits = res.data;

      const tbody = document.getElementById('visits-tbody');
      if (!cachedVisits.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:1.5rem;">No visits match the selected filters.</td></tr>`;
        return;
      }
      tbody.innerHTML = cachedVisits.map(v => `
        <tr>
          <td><b>#${v.visit_id}</b></td>
          <td><b>${v.visit_date}</b></td>
          <td>Patient #${v.patient_id} <span style="color:var(--muted);font-size:0.8rem;">(${v.age_band || ''}, ${v.gender || ''})</span></td>
          <td>${v.department_name || ('Dept #' + v.department_id)}</td>
          <td><span class="badge badge-${v.visit_type}">${v.visit_type}</span></td>
          <td>${v.notes || '<span style="color:#94a3b8;">—</span>'}</td>
          <td class="actions-cell">
            <button class="btn btn-outline btn-sm" onclick="openEditVisit(${v.visit_id})">✏️ Edit</button>
            <button class="btn btn-danger btn-sm" onclick="deleteVisit(${v.visit_id})">🗑️ Delete</button>
          </td>
        </tr>
      `).join('');
    }

    function resetVisitFilters() {
      document.getElementById('vf_dept').value = '';
      document.getElementById('vf_type').value = '';
      document.getElementById('vf_from').value = '';
      document.getElementById('vf_to').value = '';
      document.getElementById('vf_limit').value = '50';
      loadVisits();
    }

    async function submitQuickVisit(e) {
      e.preventDefault();
      await postVisitPayload({
        patient_id: parseInt(document.getElementById('qv_patient').value, 10),
        department_id: parseInt(document.getElementById('qv_dept').value, 10),
        visit_date: document.getElementById('qv_date').value,
        visit_type: document.getElementById('qv_type').value,
        notes: document.getElementById('qv_notes').value.trim()
      });
      document.getElementById('qv_notes').value = '';
    }

    async function createVisit(e) {
      e.preventDefault();
      await postVisitPayload({
        patient_id: parseInt(document.getElementById('v_patient').value, 10),
        department_id: parseInt(document.getElementById('v_dept').value, 10),
        visit_date: document.getElementById('v_date').value,
        visit_type: document.getElementById('v_type').value,
        notes: document.getElementById('v_notes').value.trim()
      });
      document.getElementById('v_notes').value = '';
    }

    async function postVisitPayload(payload) {
      const res = await fetch('/api/visits/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(r => r.json());

      if (res.status === 'success') {
        showToast(`Visit #${res.data.visit_id} recorded!`);
        await refreshEverything();
      } else {
        showToast(res.message || 'Failed to record visit', 'error');
      }
    }

    function openEditVisit(visitId) {
      const v = cachedVisits.find(x => x.visit_id === visitId);
      if (!v) return;
      currentEdit = { type: 'visit', id: visitId };
      document.getElementById('modal-title').textContent = `Edit Visit #${visitId}`;

      const ptOpts = document.getElementById('v_patient').innerHTML;
      const deptOpts = document.getElementById('v_dept').innerHTML;
      const vtypes = ['Outpatient', 'Inpatient', 'Emergency', 'Follow-up', 'Teleconsult'];

      document.getElementById('modal-fields').innerHTML = `
        <div class="form-group">
          <label>Patient *</label>
          <select id="edit_v_patient" required>${ptOpts}</select>
        </div>
        <div class="form-group">
          <label>Department *</label>
          <select id="edit_v_dept" required>${deptOpts}</select>
        </div>
        <div class="form-group">
          <label>Visit Date (YYYY-MM-DD) *</label>
          <input type="date" id="edit_v_date" value="${v.visit_date}" required>
        </div>
        <div class="form-group">
          <label>Visit Type *</label>
          <select id="edit_v_type" required>
            ${vtypes.map(t => `<option value="${t}" ${v.visit_type === t ? 'selected' : ''}>${t}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label>Notes</label>
          <input type="text" id="edit_v_notes" value="${(v.notes || '').replace(/"/g, '&quot;')}">
        </div>
      `;
      document.getElementById('edit_v_patient').value = v.patient_id;
      document.getElementById('edit_v_dept').value = v.department_id;
      document.getElementById('edit-modal').classList.add('open');
    }

    async function deleteVisit(visitId) {
      if (!confirm(`Delete Visit #${visitId}?`)) return;
      const res = await fetch(`/api/visits/${visitId}`, { method: 'DELETE' }).then(r => r.json());
      if (res.status === 'success') {
        showToast(`Visit #${visitId} deleted!`);
        await refreshEverything();
      } else {
        showToast(res.message || 'Error deleting visit', 'error');
      }
    }

    // =========================================================================
    // MODAL SUBMIT HANDLER (PUT requests for Visit / Patient / Department)
    // =========================================================================
    function closeModal() {
      document.getElementById('edit-modal').classList.remove('open');
      currentEdit = { type: null, id: null };
    }

    async function submitModalEdit(e) {
      e.preventDefault();
      const { type, id } = currentEdit;
      if (!type || !id) return;

      let url = '';
      let payload = {};

      if (type === 'visit') {
        url = `/api/visits/${id}`;
        payload = {
          patient_id: parseInt(document.getElementById('edit_v_patient').value, 10),
          department_id: parseInt(document.getElementById('edit_v_dept').value, 10),
          visit_date: document.getElementById('edit_v_date').value,
          visit_type: document.getElementById('edit_v_type').value,
          notes: document.getElementById('edit_v_notes').value.trim()
        };
      } else if (type === 'patient') {
        url = `/api/patients/${id}`;
        payload = {
          age_band: document.getElementById('edit_p_age').value,
          gender: document.getElementById('edit_p_gender').value
        };
      } else if (type === 'department') {
        url = `/api/departments/${id}`;
        payload = {
          department_name: document.getElementById('edit_d_name').value.trim(),
          description: document.getElementById('edit_d_desc').value.trim()
        };
      }

      const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(r => r.json());

      if (res.status === 'success') {
        showToast(`${type.charAt(0).toUpperCase() + type.slice(1)} #${id} updated!`);
        closeModal();
        await refreshEverything();
      } else {
        showToast(res.message || 'Update failed', 'error');
      }
    }

    // =========================================================================
    // CHARTS GENERATOR & GALLERY REFRESH
    // =========================================================================
    function refreshChartImages() {
      const ts = Date.now();
      const names = [
        ['img-c1', 'dept_workload_bar.png'],
        ['img-c2', 'monthly_visits_line.png'],
        ['img-c3', 'visit_type_pie.png'],
        ['img-c4', 'age_band_bar.png'],
        ['img-c5', 'dept_emergency_heatmap.png'],
        ['img-c6', 'day_of_week_bar.png']
      ];
      names.forEach(([id, file]) => {
        const el = document.getElementById(id);
        if (el) el.src = `/charts/${file}?t=${ts}`;
      });
    }

    async function generateAndShowCharts() {
      const st = document.getElementById('chart-status');
      st.textContent = 'Generating 6 charts...';
      try {
        const res = await fetch('/api/analysis/generate-charts', { method: 'POST' }).then(r => r.json());
        if (res.status === 'success') {
          refreshChartImages();
          st.textContent = `✅ ${res.data.length} charts updated!`;
          showToast('All 6 Matplotlib charts regenerated!');
        } else {
          st.textContent = '❌ Failed to generate charts';
        }
      } catch (e) {
        st.textContent = '❌ Error generating charts';
      }
    }

    // =========================================================================
    // INTERACTIVE API CONSOLE
    // =========================================================================
    async function quickApi(method, url) {
      document.getElementById('api_method').value = method.trim();
      document.getElementById('api_url').value = url.trim();
      await sendCustomApi();
    }

    async function sendCustomApi() {
      const method = document.getElementById('api_method').value;
      const url = document.getElementById('api_url').value.trim();
      const bodyTxt = document.getElementById('api_body').value.trim();
      const out = document.getElementById('api_response');
      out.textContent = `Sending ${method} ${url} ...`;

      const opts = { method, headers: {} };
      if ((method === 'POST' || method === 'PUT') && bodyTxt) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = bodyTxt;
      }
      try {
        const resp = await fetch(url, opts);
        const json = await resp.json();
        out.textContent = `HTTP ${resp.status} ${resp.statusText}\n\n` + JSON.stringify(json, null, 2);
        if (method !== 'GET') {
          await refreshEverything();
        }
      } catch (err) {
        out.textContent = 'Request failed: ' + err.message;
      }
    }

    function copyLanUrl() {
      const urlText = document.getElementById('lan-primary-url').textContent.trim();
      if (navigator.clipboard) {
        navigator.clipboard.writeText(urlText).then(() => showToast('Copied link: ' + urlText));
      } else {
        prompt('Copy this link to share with other laptops:', urlText);
      }
    }

    // Initial load on page ready
    window.addEventListener('DOMContentLoaded', () => {
      refreshEverything();
      generateAndShowCharts();
    });
  </script>
</body>
</html>
"""

# ==============================================================================
# WEB & HEALTH ROUTES
# ==============================================================================
@app.route("/")
def dashboard():
    tv = query_one("SELECT COUNT(*) AS c FROM visits")["c"]
    tp = query_one("SELECT COUNT(*) AS c FROM patients")["c"]
    td = query_one("SELECT COUNT(*) AS c FROM departments")["c"]
    monthly = query_all("SELECT * FROM vw_monthly_visits")
    avg_m = round(tv / max(len(monthly), 1), 1)
    ips = get_lan_ips()
    primary_url = f"http://{ips[0]}:{PORT}/"
    return render_template_string(
        HTML_DASHBOARD,
        total_visits=tv,
        total_patients=tp,
        total_depts=td,
        avg_monthly=avg_m,
        server_port=PORT,
        primary_lan_url=primary_url,
        hostname=socket.gethostname(),
        all_lan_ips=", ".join(f"http://{ip}:{PORT}/" for ip in ips),
    )


@app.route("/api/network-info", methods=["GET"])
def network_info():
    ips = get_lan_ips()
    return ok({
        "hostname": socket.gethostname(),
        "port": PORT,
        "local_url": f"http://localhost:{PORT}/",
        "lan_ips": ips,
        "shareable_urls": [f"http://{ip}:{PORT}/" for ip in ips],
    }, "Network host info retrieved")


@app.route("/health", methods=["GET"])
def health():
    try:
        cnt = query_one("SELECT COUNT(*) AS c FROM departments")["c"]
        return jsonify({
            "status": "ok",
            "db": True,
            "departments_count": cnt,
            "disclaimer": DISCLAIMER
        }), 200
    except Exception as exc:
        return jsonify({"status": "error", "db": False, "message": str(exc)}), 500


@app.route("/api/database/reset", methods=["POST"])
def reset_database_endpoint():
    """Reset and re-seed the SQLite database directly from the single app.py server."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.executescript("DROP TABLE IF EXISTS visits; DROP TABLE IF EXISTS patients; DROP TABLE IF EXISTS departments;")
        conn.commit()
    init_database(reset_existing=False)
    generate_all_charts()
    return ok({"reset": True}, "Database reset and re-seeded to initial synthetic data")


# ==============================================================================
# DEPARTMENTS CRUD API (/api/departments)
# ==============================================================================
@app.route("/api/departments/", methods=["GET"])
def list_departments():
    rows = query_all("SELECT * FROM vw_dept_workload")
    return ok(rows, "Departments retrieved")


@app.route("/api/departments/workload", methods=["GET"])
def dept_workload():
    rows = query_all("SELECT * FROM vw_dept_workload")
    return ok(rows, "Department workload retrieved")


@app.route("/api/departments/<int:dept_id>", methods=["GET"])
def get_department(dept_id: int):
    row = query_one("SELECT * FROM vw_dept_workload WHERE department_id = ?", (dept_id,))
    if not row:
        return err(f"Department #{dept_id} not found", 404)
    return ok(row, "Department retrieved")


@app.route("/api/departments/", methods=["POST"])
def create_department():
    b = request.get_json(silent=True) or {}
    name = (b.get("department_name") or "").strip()
    desc = (b.get("description") or "").strip()
    if not name:
        return err("department_name is required", 400)
    if len(name) > 100:
        return err("department_name must be 100 characters or fewer", 400)

    existing = query_one(
        "SELECT department_id FROM departments WHERE LOWER(department_name) = LOWER(?)",
        (name,),
    )
    if existing:
        return err(f"Department '{name}' already exists", 409)

    did = execute_db(
        "INSERT INTO departments (department_name, description) VALUES (?, ?)",
        (name, desc),
    )
    created = query_one("SELECT * FROM vw_dept_workload WHERE department_id = ?", (did,))
    return ok(created, "Department created", 201)


@app.route("/api/departments/<int:dept_id>", methods=["PUT"])
def update_department(dept_id: int):
    existing = query_one("SELECT * FROM departments WHERE department_id = ?", (dept_id,))
    if not existing:
        return err(f"Department #{dept_id} not found", 404)

    b = request.get_json(silent=True) or {}
    name = (b.get("department_name") if "department_name" in b else existing["department_name"] or "").strip()
    desc = (b.get("description") if "description" in b else (existing["description"] or "")).strip()

    if not name:
        return err("department_name cannot be empty", 400)

    dup = query_one(
        "SELECT department_id FROM departments WHERE LOWER(department_name) = LOWER(?) AND department_id != ?",
        (name, dept_id),
    )
    if dup:
        return err(f"Another department named '{name}' already exists", 409)

    execute_db(
        "UPDATE departments SET department_name = ?, description = ? WHERE department_id = ?",
        (name, desc, dept_id),
    )
    updated = query_one("SELECT * FROM vw_dept_workload WHERE department_id = ?", (dept_id,))
    return ok(updated, "Department updated")


@app.route("/api/departments/<int:dept_id>", methods=["DELETE"])
def delete_department(dept_id: int):
    existing = query_one("SELECT * FROM departments WHERE department_id = ?", (dept_id,))
    if not existing:
        return err(f"Department #{dept_id} not found", 404)

    visit_cnt = query_one("SELECT COUNT(*) AS c FROM visits WHERE department_id = ?", (dept_id,))["c"]
    if visit_cnt > 0:
        return err(
            f"Cannot delete department '{existing['department_name']}' because {visit_cnt} visit(s) are linked to it.",
            409,
        )

    execute_db("DELETE FROM departments WHERE department_id = ?", (dept_id,))
    return ok({"deleted_department_id": dept_id}, "Department deleted")


# ==============================================================================
# PATIENTS CRUD API (/api/patients)
# ==============================================================================
@app.route("/api/patients/", methods=["GET"])
def list_patients():
    age_band = request.args.get("age_band")
    gender = request.args.get("gender")
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 1000)
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        return err("Invalid pagination parameters", 400)
    offset = (page - 1) * limit

    where = []
    params = []
    if age_band:
        if age_band not in VALID_AGE_BANDS:
            return err(f"Invalid age_band. Must be one of {VALID_AGE_BANDS}", 400)
        where.append("p.age_band = ?")
        params.append(age_band)
    if gender:
        if gender not in VALID_GENDERS:
            return err(f"Invalid gender. Must be one of {VALID_GENDERS}", 400)
        where.append("p.gender = ?")
        params.append(gender)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT p.patient_id, p.age_band, p.gender, p.created_at,
               COUNT(v.visit_id) AS visit_count
        FROM patients p
        LEFT JOIN visits v ON p.patient_id = v.patient_id
        {where_sql}
        GROUP BY p.patient_id, p.age_band, p.gender, p.created_at
        ORDER BY p.patient_id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return ok(query_all(sql, tuple(params)), "Patients retrieved")


@app.route("/api/patients/<int:patient_id>", methods=["GET"])
def get_patient(patient_id: int):
    row = query_one(
        """
        SELECT p.patient_id, p.age_band, p.gender, p.created_at,
               COUNT(v.visit_id) AS visit_count
        FROM patients p
        LEFT JOIN visits v ON p.patient_id = v.patient_id
        WHERE p.patient_id = ?
        GROUP BY p.patient_id, p.age_band, p.gender, p.created_at
        """,
        (patient_id,),
    )
    if not row:
        return err(f"Patient #{patient_id} not found", 404)
    return ok(row, "Patient retrieved")


@app.route("/api/patients/", methods=["POST"])
def add_patient():
    b = request.get_json(silent=True) or {}
    band = b.get("age_band", "18-34")
    gender = b.get("gender", "Prefer not to say")
    if band not in VALID_AGE_BANDS:
        return err(f"Invalid age_band '{band}'. Choose from {VALID_AGE_BANDS}", 400)
    if gender not in VALID_GENDERS:
        return err(f"Invalid gender '{gender}'. Choose from {VALID_GENDERS}", 400)

    pid = execute_db(
        "INSERT INTO patients (age_band, gender) VALUES (?, ?)",
        (band, gender),
    )
    created = query_one("SELECT * FROM patients WHERE patient_id = ?", (pid,))
    return ok(created, "Patient created", 201)


@app.route("/api/patients/<int:patient_id>", methods=["PUT"])
def update_patient(patient_id: int):
    existing = query_one("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    if not existing:
        return err(f"Patient #{patient_id} not found", 404)

    b = request.get_json(silent=True) or {}
    band = b.get("age_band", existing["age_band"])
    gender = b.get("gender", existing["gender"])

    if band not in VALID_AGE_BANDS:
        return err(f"Invalid age_band '{band}'. Choose from {VALID_AGE_BANDS}", 400)
    if gender not in VALID_GENDERS:
        return err(f"Invalid gender '{gender}'. Choose from {VALID_GENDERS}", 400)

    execute_db(
        "UPDATE patients SET age_band = ?, gender = ? WHERE patient_id = ?",
        (band, gender, patient_id),
    )
    updated = query_one("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    return ok(updated, "Patient updated")


@app.route("/api/patients/<int:patient_id>", methods=["DELETE"])
def delete_patient(patient_id: int):
    existing = query_one("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    if not existing:
        return err(f"Patient #{patient_id} not found", 404)

    visit_cnt = query_one("SELECT COUNT(*) AS c FROM visits WHERE patient_id = ?", (patient_id,))["c"]
    if visit_cnt > 0:
        return err(
            f"Cannot delete Patient #{patient_id} because {visit_cnt} visit record(s) are linked to this patient.",
            409,
        )

    execute_db("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
    return ok({"deleted_patient_id": patient_id}, "Patient deleted")


@app.route("/api/patients/summary/age-bands", methods=["GET"])
def patient_age_band_summary():
    rows = query_all("SELECT * FROM vw_age_band_summary")
    return ok(rows, "Age-band summary retrieved")


# ==============================================================================
# VISITS CRUD API (/api/visits)
# ==============================================================================
@app.route("/api/visits/", methods=["GET"])
def list_visits():
    dept_id = request.args.get("dept_id")
    patient_id = request.args.get("patient_id")
    visit_type = request.args.get("visit_type")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 1000)
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        return err("Invalid pagination parameters", 400)
    offset = (page - 1) * limit

    where = []
    params = []

    if dept_id:
        try:
            where.append("v.department_id = ?")
            params.append(int(dept_id))
        except ValueError:
            return err("dept_id must be an integer", 400)

    if patient_id:
        try:
            where.append("v.patient_id = ?")
            params.append(int(patient_id))
        except ValueError:
            return err("patient_id must be an integer", 400)

    if visit_type:
        if visit_type not in VALID_VISIT_TYPES:
            return err(f"Invalid visit_type. Choose from {VALID_VISIT_TYPES}", 400)
        where.append("v.visit_type = ?")
        params.append(visit_type)

    if date_from:
        if not DATE_RE.match(date_from):
            return err("date_from must be YYYY-MM-DD", 400)
        where.append("v.visit_date >= ?")
        params.append(date_from)

    if date_to:
        if not DATE_RE.match(date_to):
            return err("date_to must be YYYY-MM-DD", 400)
        where.append("v.visit_date <= ?")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT v.visit_id, v.patient_id, v.department_id,
               d.department_name, p.age_band, p.gender,
               v.visit_date, v.visit_type, v.notes, v.created_at
        FROM visits v
        JOIN departments d ON v.department_id = d.department_id
        JOIN patients    p ON v.patient_id    = p.patient_id
        {where_sql}
        ORDER BY v.visit_date DESC, v.visit_id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return ok(query_all(sql, tuple(params)), "Visits retrieved")


@app.route("/api/visits/<int:visit_id>", methods=["GET"])
def get_visit(visit_id: int):
    row = query_one(
        """
        SELECT v.visit_id, v.patient_id, v.department_id,
               d.department_name, p.age_band, p.gender,
               v.visit_date, v.visit_type, v.notes, v.created_at
        FROM visits v
        JOIN departments d ON v.department_id = d.department_id
        JOIN patients    p ON v.patient_id    = p.patient_id
        WHERE v.visit_id = ?
        """,
        (visit_id,),
    )
    if not row:
        return err(f"Visit #{visit_id} not found", 404)
    return ok(row, "Visit retrieved")


def _validate_visit_fields(pid, did, dt, vt):
    if pid is None or did is None or not dt or not vt:
        return "patient_id, department_id, visit_date, and visit_type are required"
    try:
        pid = int(pid)
        did = int(did)
    except (ValueError, TypeError):
        return "patient_id and department_id must be integers"

    if not DATE_RE.match(str(dt)):
        return "visit_date must be in YYYY-MM-DD format"
    try:
        datetime.strptime(str(dt), "%Y-%m-%d")
    except ValueError:
        return f"Invalid calendar date '{dt}'"

    if vt not in VALID_VISIT_TYPES:
        return f"Invalid visit_type '{vt}'. Choose from {VALID_VISIT_TYPES}"

    if not query_one("SELECT patient_id FROM patients WHERE patient_id = ?", (pid,)):
        return f"Patient #{pid} does not exist"
    if not query_one("SELECT department_id FROM departments WHERE department_id = ?", (did,)):
        return f"Department #{did} does not exist"
    return None


@app.route("/api/visits/", methods=["POST"])
def add_visit():
    b = request.get_json(silent=True) or {}
    pid = b.get("patient_id")
    did = b.get("department_id")
    dt = b.get("visit_date")
    vt = b.get("visit_type")
    notes = (b.get("notes") or "").strip() or None

    validation_error = _validate_visit_fields(pid, did, dt, vt)
    if validation_error:
        return err(validation_error, 400)

    vid = execute_db(
        "INSERT INTO visits (patient_id, department_id, visit_date, visit_type, notes) VALUES (?, ?, ?, ?, ?)",
        (int(pid), int(did), str(dt), vt, notes),
    )
    created = query_one(
        """
        SELECT v.visit_id, v.patient_id, v.department_id,
               d.department_name, p.age_band, p.gender,
               v.visit_date, v.visit_type, v.notes, v.created_at
        FROM visits v
        JOIN departments d ON v.department_id = d.department_id
        JOIN patients    p ON v.patient_id    = p.patient_id
        WHERE v.visit_id = ?
        """,
        (vid,),
    )
    return ok(created, "Visit recorded", 201)


@app.route("/api/visits/<int:visit_id>", methods=["PUT"])
def update_visit(visit_id: int):
    existing = query_one("SELECT * FROM visits WHERE visit_id = ?", (visit_id,))
    if not existing:
        return err(f"Visit #{visit_id} not found", 404)

    b = request.get_json(silent=True) or {}
    pid = b.get("patient_id", existing["patient_id"])
    did = b.get("department_id", existing["department_id"])
    dt = b.get("visit_date", existing["visit_date"])
    vt = b.get("visit_type", existing["visit_type"])
    notes = b.get("notes", existing["notes"])
    if isinstance(notes, str):
        notes = notes.strip() or None

    validation_error = _validate_visit_fields(pid, did, dt, vt)
    if validation_error:
        return err(validation_error, 400)

    execute_db(
        """
        UPDATE visits
        SET patient_id = ?, department_id = ?, visit_date = ?, visit_type = ?, notes = ?
        WHERE visit_id = ?
        """,
        (int(pid), int(did), str(dt), vt, notes, visit_id),
    )
    updated = query_one(
        """
        SELECT v.visit_id, v.patient_id, v.department_id,
               d.department_name, p.age_band, p.gender,
               v.visit_date, v.visit_type, v.notes, v.created_at
        FROM visits v
        JOIN departments d ON v.department_id = d.department_id
        JOIN patients    p ON v.patient_id    = p.patient_id
        WHERE v.visit_id = ?
        """,
        (visit_id,),
    )
    return ok(updated, "Visit updated")


@app.route("/api/visits/<int:visit_id>", methods=["DELETE"])
def delete_visit(visit_id: int):
    existing = query_one("SELECT visit_id FROM visits WHERE visit_id = ?", (visit_id,))
    if not existing:
        return err(f"Visit #{visit_id} not found", 404)

    execute_db("DELETE FROM visits WHERE visit_id = ?", (visit_id,))
    return ok({"deleted_visit_id": visit_id}, "Visit deleted")


@app.route("/api/visits/summary/monthly", methods=["GET"])
def visits_monthly_summary():
    return ok(query_all("SELECT * FROM vw_monthly_visits"), "Monthly visit counts retrieved")


@app.route("/api/visits/summary/daily", methods=["GET"])
def visits_daily_summary():
    month = request.args.get("month")
    if month:
        if not MONTH_RE.match(month):
            return err("month parameter must be YYYY-MM", 400)
        rows = query_all(
            """
            SELECT visit_date, COUNT(*) AS total_visits
            FROM visits
            WHERE strftime('%Y-%m', visit_date) = ?
            GROUP BY visit_date
            ORDER BY visit_date ASC
            """,
            (month,),
        )
    else:
        rows = query_all(
            """
            SELECT visit_date, COUNT(*) AS total_visits
            FROM visits
            GROUP BY visit_date
            ORDER BY visit_date DESC
            LIMIT 60
            """
        )
    return ok(rows, "Daily visit counts retrieved")


# ==============================================================================
# ANALYTICS & CHARTS API (/api/analysis)
# ==============================================================================
@app.route("/api/analysis/summary", methods=["GET"])
def analysis_summary():
    df = get_dataframe()
    total_pts = query_one("SELECT COUNT(*) AS c FROM patients")["c"]
    total_depts = query_one("SELECT COUNT(*) AS c FROM departments")["c"]

    if df.empty:
        return ok({
            "total_visits": 0,
            "unique_patients_visited": 0,
            "total_registered_patients": total_pts,
            "total_departments": total_depts,
            "emergency_rate_pct": 0.0,
            "monthly_stats": {"mean": 0.0, "median": 0.0, "std": 0.0, "min": 0, "max": 0},
            "visit_type_breakdown": {},
            "age_band_breakdown": {},
        })

    monthly = df.groupby("year_month").size().values
    emg_cnt = int((df["visit_type"] == "Emergency").sum())

    return ok({
        "total_visits": int(len(df)),
        "unique_patients_visited": int(df["patient_id"].nunique()),
        "total_registered_patients": int(total_pts),
        "total_departments": int(total_depts),
        "emergency_rate_pct": round((emg_cnt / len(df)) * 100.0, 2),
        "monthly_stats": {
            "mean": round(float(np.mean(monthly)), 2),
            "median": round(float(np.median(monthly)), 2),
            "std": round(float(np.std(monthly)), 2),
            "min": int(np.min(monthly)),
            "max": int(np.max(monthly)),
            "p25": round(float(np.percentile(monthly, 25)), 2),
            "p75": round(float(np.percentile(monthly, 75)), 2),
        },
        "visit_type_breakdown": {k: int(v) for k, v in df["visit_type"].value_counts().items()},
        "age_band_breakdown": {
            k: int(v) for k, v in df["age_band"].value_counts().reindex(VALID_AGE_BANDS, fill_value=0).items()
        },
    })


@app.route("/api/analysis/department-workload", methods=["GET"])
def analysis_dept_workload():
    rows = query_all("SELECT * FROM vw_dept_workload")
    if not rows:
        return ok({"departments": [], "mean_visits": 0.0, "std_visits": 0.0})

    counts = np.array([r["total_visits"] for r in rows], dtype=float)
    total_all = max(float(np.sum(counts)), 1.0)
    mean_v = float(np.mean(counts))
    std_v = float(np.std(counts))

    enriched = []
    for r in rows:
        c = float(r["total_visits"])
        z = round((c - mean_v) / std_v, 2) if std_v > 0 else 0.0
        item = dict(r)
        item["share_pct"] = round((c / total_all) * 100.0, 1)
        item["z_score"] = z
        enriched.append(item)

    return ok({
        "mean_visits": round(mean_v, 2),
        "std_visits": round(std_v, 2),
        "departments": enriched,
    })


@app.route("/api/analysis/monthly-trends", methods=["GET"])
def analysis_monthly_trends():
    rows = query_all("SELECT * FROM vw_monthly_visits ORDER BY year_month ASC")
    if not rows:
        return ok({"months": [], "linear_slope": 0.0, "trend_direction": "Stable"})

    s = pd.Series([r["total_visits"] for r in rows], dtype=float)
    pct_changes = s.pct_change() * 100.0

    months_out = []
    for idx, r in enumerate(rows):
        mom = None if pd.isna(pct_changes.iloc[idx]) else round(float(pct_changes.iloc[idx]), 2)
        months_out.append({
            "year_month": r["year_month"],
            "total_visits": int(r["total_visits"]),
            "mom_change_pct": mom,
        })

    if len(rows) >= 2:
        x = np.arange(len(rows), dtype=float)
        slope = float(np.polyfit(x, s.values, 1)[0])
    else:
        slope = 0.0

    if slope > 0.15:
        direction = "Increasing"
    elif slope < -0.15:
        direction = "Decreasing"
    else:
        direction = "Stable"

    return ok({
        "linear_slope": round(slope, 3),
        "trend_direction": direction,
        "months": months_out,
    })


@app.route("/api/analysis/age-band", methods=["GET"])
def analysis_age_band():
    rows = query_all("""
        SELECT p.age_band,
               COUNT(DISTINCT p.patient_id) AS registered_patients,
               COUNT(v.visit_id) AS total_visits
        FROM patients p
        LEFT JOIN visits v ON p.patient_id = v.patient_id
        GROUP BY p.age_band
    """)
    by_band = {r["age_band"]: r for r in rows}
    total_v = max(sum(r["total_visits"] for r in rows), 1)

    result = []
    for band in VALID_AGE_BANDS:
        r = by_band.get(band, {"age_band": band, "registered_patients": 0, "total_visits": 0})
        tv = int(r["total_visits"])
        rp = int(r["registered_patients"])
        result.append({
            "age_band": band,
            "registered_patients": rp,
            "total_visits": tv,
            "visit_share_pct": round((tv / total_v) * 100.0, 1),
        })
    return ok(result, "Age-band analysis retrieved")


@app.route("/api/analysis/generate-charts", methods=["POST"])
def trigger_charts():
    generated = generate_all_charts()
    return ok(generated, f"{len(generated)} charts generated successfully")


@app.route("/charts/<path:filename>", methods=["GET"])
@app.route("/api/analysis/charts/<path:filename>", methods=["GET"])
def get_chart_img(filename):
    full_path = os.path.join(CHARTS_DIR, filename)
    if not os.path.exists(full_path):
        generate_all_charts()
    return send_from_directory(CHARTS_DIR, filename)


# ------------------------------------------------------------------------------
# MAIN EXECUTION ENTRY POINT
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    if "--reset-db" in sys.argv:
        print("Resetting database to initial synthetic seed data...")
        init_database(reset_existing=True)

    generate_all_charts()
    lan_ips = get_lan_ips()
    local_url = f"http://localhost:{PORT}/"

    print("\n" + "=" * 74)
    print("  🏥 HOSPITAL PATIENT DATA ANALYSIS SYSTEM — ALL-IN-ONE VS CODE EDITION")
    print("=" * 74)
    print(f"  💻 On THIS Laptop:         {local_url}")
    for ip in lan_ips:
        print(f"  🌐 On OTHER Laptops/Wi-Fi: http://{ip}:{PORT}/")
    print("-" * 74)
    print("  ℹ️  Make sure other laptops are on the same Wi-Fi or Mobile Hotspot.")
    print(f"  🛡️  If Windows Firewall blocks other laptops, run in Admin CMD:")
    print(f'      netsh advfirewall firewall add rule name="HospitalApp" dir=in action=allow protocol=TCP localport={PORT}')
    print("=" * 74 + "\n")

    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)