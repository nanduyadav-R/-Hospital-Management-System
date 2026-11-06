# Hospital Patient Data Analysis System

> **IMPORTANT — Operational Statistics Only**
> All outputs are educational operational analytics. This system uses **synthetic / de-identified data only** and does **not** produce clinical advice, diagnoses, or treatment recommendations.

---

## Project Overview

A Flask-based REST API system for analysing de-identified hospital visit data. The system supports full CRUD operations on patients, departments, and visits; runs Pandas/NumPy analyses; and produces Matplotlib visualisations.

**Tech stack:** Python 3.12+, Flask 3.x, MySQL 8 / SQLite (dev), Pandas, NumPy, Matplotlib, pytest

---

## Quick Start

### 1. Prerequisites
- Python 3.12+
- MySQL 8.x (optional — SQLite works out of the box for development)

### 2. Environment Setup

```bash
# Clone / extract the project
cd hospital_system

# Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
copy .env.example .env
# Edit .env and fill in your database credentials
```

`.env` variables:

| Variable | Default | Description |
|---|---|---|
| `DB_ENGINE` | `sqlite` | `sqlite` or `mysql` |
| `DB_HOST` | `localhost` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_NAME` | `hospital_analytics` | Database name |
| `DB_USER` | `root` | MySQL username |
| `DB_PASSWORD` | _(empty)_ | MySQL password |
| `SECRET_KEY` | dev-secret | Flask secret key |
| `CHARTS_DIR` | `charts` | Output directory for chart images |

### 4. Database Setup (MySQL)

```bash
# In MySQL Workbench or CLI:
mysql -u root -p < sql/schema_and_seed.sql
```

Then set `DB_ENGINE=mysql` in `.env`.

### 5. Run the Application

```bash
# Start Flask dev server
py run.py

# Run analysis report (standalone, no server)
py run.py --analysis

# Generate all charts (standalone)
py run.py --charts

# All in one (analysis + charts + server)
py run.py --all
```

Server starts at **http://127.0.0.1:5000**

---

## API Endpoint Reference

All API routes are prefixed with `/api/`. All responses include a `disclaimer` field labelling outputs as operational statistics.

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health + DB connectivity |

### Departments

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/departments/` | List all departments |
| GET | `/api/departments/<id>` | Get one department |
| POST | `/api/departments/` | Create department |
| PUT | `/api/departments/<id>` | Update department name |
| DELETE | `/api/departments/<id>` | Delete (blocked if visits exist) |
| GET | `/api/departments/workload` | Dept-wise visit workload |

**POST / PUT body:**
```json
{ "department_name": "Cardiology", "description": "Heart and vascular" }
```

### Patients (De-identified)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/patients/` | List patients (paginated) |
| GET | `/api/patients/<id>` | Get one patient |
| POST | `/api/patients/` | Create patient record |
| PUT | `/api/patients/<id>` | Update record |
| DELETE | `/api/patients/<id>` | Delete (blocked if visits exist) |
| GET | `/api/patients/summary/age-bands` | Age-band aggregated summary |

**POST body:**
```json
{ "age_band": "18-34", "gender": "M" }
```

Valid `age_band` values: `0-17`, `18-34`, `35-49`, `50-64`, `65+`
Valid `gender` values: `M`, `F`, `Other`, `Prefer not to say`

### Visits

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/visits/` | List visits (filterable) |
| GET | `/api/visits/<id>` | Get one visit |
| POST | `/api/visits/` | Record a new visit |
| PUT | `/api/visits/<id>` | Update a visit |
| DELETE | `/api/visits/<id>` | Delete a visit |
| GET | `/api/visits/summary/monthly` | Monthly visit counts |
| GET | `/api/visits/summary/daily?month=YYYY-MM` | Daily counts for a month |

**Query filters (GET /api/visits/):**
- `dept_id` — filter by department ID (integer)
- `date_from` — filter start date (YYYY-MM-DD)
- `date_to` — filter end date (YYYY-MM-DD)
- `visit_type` — one of `Outpatient`, `Inpatient`, `Emergency`, `Follow-up`, `Teleconsult`
- `page`, `limit` — pagination

**POST body:**
```json
{
  "patient_id": 1,
  "department_id": 2,
  "visit_date": "2024-06-15",
  "visit_type": "Outpatient",
  "notes": "Routine follow-up"
}
```

### Analytics & Data Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analysis/summary` | Overall KPIs + NumPy stats |
| GET | `/api/analysis/department-workload` | Per-dept workload with z-scores |
| GET | `/api/analysis/monthly-trends` | MoM trend + linear trend direction |
| GET | `/api/analysis/age-band` | Age-band visit distribution |
| POST | `/api/analysis/generate-charts` | Generate all 6 Matplotlib charts |
| GET | `/api/analysis/charts/<filename>` | Serve a chart image |

---

## Database Schema

### Tables

```
patients(patient_id PK, age_band, gender)
departments(department_id PK, department_name UNIQUE, description)
visits(visit_id PK, patient_id FK, department_id FK, visit_date, visit_type, notes)
```

### Views

| View | Purpose |
|------|---------|
| `vw_dept_workload` | Per-department visit counts by type |
| `vw_monthly_visits` | Month-by-month visit counts |
| `vw_age_band_summary` | Age-band aggregated visit/patient counts |

### ER Diagram (text)

```
patients (1) ──── (M) visits (M) ──── (1) departments
```

---

## Data Analysis Methodology (D4)

All analysis is performed by `analysis/charts.py` using Pandas + NumPy:

| Metric | Formula |
|--------|---------|
| Monthly mean | `np.mean(monthly_counts)` |
| Std deviation | `np.std(monthly_counts)` (population) |
| Z-score per dept | `(x - mean) / std` |
| Month-over-month change | `series.pct_change() * 100` |
| Linear trend direction | `np.polyfit(x, y, 1)[0] > 0` |
| Visit-type share | `count / total * 100` |

**Assumptions:**
- All patient records are synthetic; no real personal data is used.
- Age bands are fixed non-overlapping buckets.
- SQLite is used for local development; MySQL for production.

---

## Charts (D5)

Six charts are generated by `POST /api/analysis/generate-charts`:

| # | File | Chart type | Content |
|---|------|------------|---------|
| 1 | `dept_workload_bar.png` | Horizontal bar | Visit count per department |
| 2 | `monthly_visits_line.png` | Line + trend | Monthly visit trend with linear fit |
| 3 | `visit_type_pie.png` | Pie | Visit-type distribution % |
| 4 | `age_band_bar.png` | Vertical bar | Visits by age band |
| 5 | `dept_emergency_heatmap.png` | Grouped bar | Total vs emergency per department |
| 6 | `day_of_week_bar.png` | Bar | Visit volume by day of week |

All charts include: title, axis labels, units, data labels, and disclaimer footer.

---

## Testing (D6)

```bash
py -m pytest tests/test_hospital.py -v
```

**62 test cases across 8 test classes:**

| Class | Tests | Covers |
|-------|-------|--------|
| `TestHealthEndpoint` | 3 | DB up/down, disclaimer |
| `TestDepartmentsAPI` | 8 | Full CRUD, duplicate, conflict |
| `TestPatientsAPI` | 9 | Full CRUD, pagination, boundary |
| `TestVisitsAPI` | 11 | CRUD, filters, bad input |
| `TestValidators` | 12 | All validators, boundary values |
| `TestAnalysisModule` | 6 | Chart functions, file output |
| `TestNumpyStats` | 7 | Mean, std, percentile, empty, single-row |
| `TestAnalysisAPI` | 6 | Endpoints, empty DB, disclaimer |

---

## Project Structure

```
hospital_system/
├── app/
│   ├── __init__.py          # Application factory
│   ├── models/
│   │   └── db.py            # DB adapter (SQLite + MySQL)
│   ├── routes/
│   │   ├── health.py        # GET /health
│   │   ├── departments.py   # /api/departments CRUD
│   │   ├── patients.py      # /api/patients CRUD
│   │   ├── visits.py        # /api/visits CRUD + summaries
│   │   ├── analysis.py      # /api/analysis — Pandas/NumPy endpoints
│   │   └── dashboard.py     # Dashboard HTML view
│   └── utils/
│       ├── validators.py    # Input validation helpers
│       └── responses.py     # Standard JSON envelopes
├── analysis/
│   ├── charts.py            # Matplotlib chart functions (6 charts)
│   ├── analysis.py          # Standalone analysis script
│   └── report.py            # Plain-text report generator
├── sql/
│   └── schema_and_seed.sql  # MySQL DDL + 350 synthetic visit records
├── tests/
│   └── test_hospital.py     # 62 pytest test cases
├── templates/               # HTML dashboard
├── static/                  # CSS / JS
├── charts/                  # Generated chart images (gitignored)
├── config.py                # Config class (env-var backed)
├── run.py                   # Entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## Limitations

- **Synthetic data only** — analysis results do not represent real clinical situations.
- **No authentication** — add session or token auth before any production deployment.
- **SQLite** does not support `DATE_FORMAT()`; the adapter translates queries automatically.
- Chart files are saved to disk and served statically; consider object storage for scale.
- All outputs are **operational statistics for educational purposes only**.

---

## Demo Checklist (Expo)

- [ ] `py run.py` starts without errors
- [ ] `GET /health` returns 200
- [ ] Create a patient, create a visit, verify in list
- [ ] `GET /api/analysis/summary` returns NumPy-backed KPIs
- [ ] `POST /api/analysis/generate-charts` produces 6 PNG files
- [ ] `py -m pytest tests/ -v` → 62 passed
- [ ] Explain schema, API routes, analysis methodology, and chart interpretations
