"""
Deliverable D4: Data Analysis Module (Pandas & NumPy)
Hospital Patient Data Analysis System (Project 7)

Performs de-identified operational analytics on hospital visits:
1. Department-wise workload summary (visit volume, unique patients, repeat visit ratio,
   workload share %, daily mean/std/median/IQR/90th percentile via NumPy).
2. Monthly and daily visit trends (chronological aggregation, month-over-month % growth,
   3-month rolling average, peak day identification, visit type breakdown).
3. Age-band demographic summary (non-identifying aggregated visit counts, unique patient counts,
   visits per patient ratio, and primary department utilization per age band).

All outputs are strictly aggregate operational statistics and carry explicit non-clinical labels.
"""
import numpy as np
import pandas as pd
from datetime import datetime
from config import Config
from db import execute_query


def load_operational_dataframes(start_date=None, end_date=None, department_id=None, db_path_override=None):
    """
    Loads patients, departments, and visits from the relational database into Pandas DataFrames,
    applies data cleaning and optional date/department filters, and returns merged operational records.
    """
    patients_rows = execute_query("SELECT patient_id, age_band, gender_optional FROM patients", db_path_override=db_path_override)
    dept_rows = execute_query("SELECT department_id, department_name FROM departments", db_path_override=db_path_override)
    visit_rows = execute_query(
        "SELECT visit_id, patient_id, department_id, visit_date, visit_type FROM visits",
        db_path_override=db_path_override
    )

    df_patients = pd.DataFrame(patients_rows) if patients_rows else pd.DataFrame(
        columns=["patient_id", "age_band", "gender_optional"]
    )
    df_depts = pd.DataFrame(dept_rows) if dept_rows else pd.DataFrame(
        columns=["department_id", "department_name"]
    )
    df_visits = pd.DataFrame(visit_rows) if visit_rows else pd.DataFrame(
        columns=["visit_id", "patient_id", "department_id", "visit_date", "visit_type"]
    )

    if df_visits.empty:
        df_merged = pd.DataFrame(columns=[
            "visit_id", "patient_id", "department_id", "visit_date", "visit_type",
            "age_band", "gender_optional", "department_name", "year_month", "day_of_week"
        ])
        return df_patients, df_depts, df_visits, df_merged

    # Data Cleaning & Standardization
    df_visits["visit_date"] = pd.to_datetime(df_visits["visit_date"], errors="coerce")
    df_visits = df_visits.dropna(subset=["visit_date", "patient_id", "department_id"])

    if not df_patients.empty:
        df_patients["gender_optional"] = df_patients["gender_optional"].fillna("Unspecified")
        df_patients["age_band"] = df_patients["age_band"].where(
            df_patients["age_band"].isin(Config.VALID_AGE_BANDS), "Unknown"
        )

    # Apply Optional Filters
    if start_date:
        start_dt = pd.to_datetime(start_date, errors="coerce")
        if pd.notna(start_dt):
            df_visits = df_visits[df_visits["visit_date"] >= start_dt]
    if end_date:
        end_dt = pd.to_datetime(end_date, errors="coerce")
        if pd.notna(end_dt):
            df_visits = df_visits[df_visits["visit_date"] <= end_dt]
    if department_id is not None:
        df_visits = df_visits[df_visits["department_id"] == int(department_id)]

    # Relational Joins via Pandas merge
    df_merged = df_visits.merge(df_patients, on="patient_id", how="left").merge(
        df_depts, on="department_id", how="left"
    )
    df_merged["year_month"] = df_merged["visit_date"].dt.strftime("%Y-%m")
    df_merged["day_of_week"] = df_merged["visit_date"].dt.day_name()

    return df_patients, df_depts, df_visits, df_merged


def analyze_department_workload(start_date=None, end_date=None, db_path_override=None):
    """
    Computes department-wise operational workload metrics using Pandas groupby and NumPy statistics:
    - total_visits: count of visits in department
    - unique_patients: distinct de-identified patient_ids served
    - workload_share_pct: (Dept Visits / Total Hospital Visits) * 100
    - visits_per_patient: Dept Visits / Unique Patients
    - emergency_visit_pct: % of visits in department classified as 'Emergency'
    - daily_mean_visits, daily_std_visits, daily_median_visits, daily_p90_visits (across active hospital days)
    """
    _, df_depts, _, df_merged = load_operational_dataframes(
        start_date=start_date, end_date=end_date, db_path_override=db_path_override
    )

    if df_merged.empty:
        return {
            "disclaimer": Config.OPERATIONAL_DISCLAIMER,
            "total_hospital_visits": 0,
            "active_days_count": 0,
            "departments": [],
            "numpy_hospital_summary": {}
        }

    total_visits_all = int(len(df_merged))
    all_active_dates = pd.date_range(df_merged["visit_date"].min(), df_merged["visit_date"].max(), freq="D")
    num_calendar_days = max(len(all_active_dates), 1)

    # Group by department
    grouped = df_merged.groupby(["department_id", "department_name"], as_index=False).agg(
        total_visits=("visit_id", "count"),
        unique_patients=("patient_id", "nunique"),
        emergency_visits=("visit_type", lambda s: int((s == "Emergency").sum())),
        outpatient_visits=("visit_type", lambda s: int((s == "Outpatient").sum())),
        followup_visits=("visit_type", lambda s: int((s == "Follow-up").sum())),
        inpatient_visits=("visit_type", lambda s: int((s == "Inpatient").sum())),
    )

    # Include any zero-visit departments from master table
    if not df_depts.empty:
        grouped = df_depts.merge(grouped, on=["department_id", "department_name"], how="left").fillna(0)
        for col in ["total_visits", "unique_patients", "emergency_visits", "outpatient_visits", "followup_visits", "inpatient_visits"]:
            grouped[col] = grouped[col].astype(int)

    # Compute daily distribution per department over the calendar span using NumPy
    dept_records = []
    for _, row in grouped.sort_values(by="total_visits", ascending=False).iterrows():
        did = int(row["department_id"])
        dname = row["department_name"]
        t_visits = int(row["total_visits"])
        u_patients = int(row["unique_patients"])

        dept_sub = df_merged[df_merged["department_id"] == did]
        if not dept_sub.empty:
            daily_counts_series = dept_sub.groupby(dept_sub["visit_date"].dt.date)["visit_id"].count()
            # Reindex across all calendar days in range (filling 0 for days with 0 visits in that dept)
            full_daily_counts = np.zeros(num_calendar_days, dtype=float)
            full_daily_counts[:len(daily_counts_series)] = daily_counts_series.values
            active_day_vals = daily_counts_series.values.astype(float)
        else:
            full_daily_counts = np.zeros(num_calendar_days, dtype=float)
            active_day_vals = np.array([0.0])

        share_pct = float(np.round((t_visits / total_visits_all) * 100.0, 2)) if total_visits_all > 0 else 0.0
        v_per_pat = float(np.round(t_visits / u_patients, 2)) if u_patients > 0 else 0.0
        emerg_pct = float(np.round((int(row["emergency_visits"]) / t_visits) * 100.0, 2)) if t_visits > 0 else 0.0

        dept_records.append({
            "department_id": did,
            "department_name": dname,
            "total_visits": t_visits,
            "unique_patients": u_patients,
            "workload_share_pct": share_pct,
            "visits_per_patient": v_per_pat,
            "emergency_visits": int(row["emergency_visits"]),
            "outpatient_visits": int(row["outpatient_visits"]),
            "followup_visits": int(row["followup_visits"]),
            "inpatient_visits": int(row["inpatient_visits"]),
            "emergency_share_pct": emerg_pct,
            "daily_mean_calendar": float(np.round(np.mean(full_daily_counts), 2)),
            "daily_std_calendar": float(np.round(np.std(full_daily_counts, ddof=0), 2)),
            "active_day_mean": float(np.round(np.mean(active_day_vals), 2)),
            "active_day_median": float(np.round(np.median(active_day_vals), 2)),
            "active_day_max": int(np.max(active_day_vals)),
        })

    # Hospital-wide NumPy summary across departments
    dept_totals_arr = np.array([d["total_visits"] for d in dept_records], dtype=float)
    numpy_summary = {
        "mean_visits_per_department": float(np.round(np.mean(dept_totals_arr), 2)),
        "median_visits_per_department": float(np.round(np.median(dept_totals_arr), 2)),
        "std_visits_per_department": float(np.round(np.std(dept_totals_arr, ddof=0), 2)),
        "min_department_visits": int(np.min(dept_totals_arr)),
        "max_department_visits": int(np.max(dept_totals_arr)),
        "iqr_department_visits": float(np.round(np.percentile(dept_totals_arr, 75) - np.percentile(dept_totals_arr, 25), 2)),
    }

    return {
        "disclaimer": Config.OPERATIONAL_DISCLAIMER,
        "total_hospital_visits": total_visits_all,
        "calendar_days_span": num_calendar_days,
        "departments": dept_records,
        "numpy_hospital_summary": numpy_summary,
    }


def analyze_visit_trends(start_date=None, end_date=None, department_id=None, db_path_override=None):
    """
    Summarizes monthly and daily visit trends using Pandas time-series grouping and NumPy statistics:
    - Monthly total visits, unique patients, Month-over-Month (MoM) growth %, 3-month rolling average
    - Visit type composition by month
    - Daily summary statistics (mean, median, std, min, max, 90th percentile, IQR)
    - Day-of-week operational distribution
    """
    _, _, _, df_merged = load_operational_dataframes(
        start_date=start_date, end_date=end_date, department_id=department_id, db_path_override=db_path_override
    )

    if df_merged.empty:
        return {
            "disclaimer": Config.OPERATIONAL_DISCLAIMER,
            "monthly_trends": [],
            "daily_statistics": {},
            "day_of_week_summary": [],
            "visit_type_summary": []
        }

    # 1. Monthly Aggregation
    monthly = df_merged.groupby("year_month", as_index=False).agg(
        total_visits=("visit_id", "count"),
        unique_patients=("patient_id", "nunique"),
        emergency_visits=("visit_type", lambda s: int((s == "Emergency").sum())),
        outpatient_visits=("visit_type", lambda s: int((s == "Outpatient").sum())),
        followup_visits=("visit_type", lambda s: int((s == "Follow-up").sum())),
        inpatient_visits=("visit_type", lambda s: int((s == "Inpatient").sum())),
    ).sort_values("year_month")

    monthly["mom_growth_pct"] = monthly["total_visits"].pct_change().multiply(100).round(2)
    monthly["rolling_3m_avg"] = monthly["total_visits"].rolling(window=3, min_periods=1).mean().round(2)

    monthly_records = []
    for _, row in monthly.iterrows():
        mom = None if pd.isna(row["mom_growth_pct"]) else float(row["mom_growth_pct"])
        monthly_records.append({
            "year_month": str(row["year_month"]),
            "total_visits": int(row["total_visits"]),
            "unique_patients": int(row["unique_patients"]),
            "emergency_visits": int(row["emergency_visits"]),
            "outpatient_visits": int(row["outpatient_visits"]),
            "followup_visits": int(row["followup_visits"]),
            "inpatient_visits": int(row["inpatient_visits"]),
            "mom_growth_pct": mom,
            "rolling_3m_avg": float(row["rolling_3m_avg"]),
        })

    # 2. Daily Visit Statistics via NumPy
    daily_series = df_merged.groupby(df_merged["visit_date"].dt.strftime("%Y-%m-%d"))["visit_id"].count()
    daily_vals = daily_series.values.astype(float)
    peak_date = str(daily_series.idxmax())
    peak_count = int(daily_series.max())

    daily_stats = {
        "active_days_recorded": int(len(daily_vals)),
        "mean_daily_visits": float(np.round(np.mean(daily_vals), 2)),
        "median_daily_visits": float(np.round(np.median(daily_vals), 2)),
        "std_daily_visits": float(np.round(np.std(daily_vals, ddof=0), 2)),
        "min_daily_visits": int(np.min(daily_vals)),
        "max_daily_visits": int(np.max(daily_vals)),
        "p90_daily_visits": float(np.round(np.percentile(daily_vals, 90), 2)),
        "iqr_daily_visits": float(np.round(np.percentile(daily_vals, 75) - np.percentile(daily_vals, 25), 2)),
        "peak_visit_date": peak_date,
        "peak_visit_count": peak_count,
    }

    # 3. Day-of-Week Operational Distribution
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_counts = df_merged.groupby("day_of_week")["visit_id"].count().reindex(dow_order, fill_value=0)
    total_v = int(len(df_merged))
    dow_records = [
        {
            "day_of_week": day,
            "visit_count": int(cnt),
            "share_pct": float(np.round((cnt / total_v) * 100.0, 2)) if total_v > 0 else 0.0
        }
        for day, cnt in dow_counts.items()
    ]

    # 4. Visit Type Breakdown
    vt_counts = df_merged.groupby("visit_type")["visit_id"].count().sort_values(ascending=False)
    vt_records = [
        {
            "visit_type": str(vt),
            "visit_count": int(cnt),
            "share_pct": float(np.round((cnt / total_v) * 100.0, 2)) if total_v > 0 else 0.0
        }
        for vt, cnt in vt_counts.items()
    ]

    return {
        "disclaimer": Config.OPERATIONAL_DISCLAIMER,
        "monthly_trends": monthly_records,
        "daily_statistics": daily_stats,
        "day_of_week_summary": dow_records,
        "visit_type_summary": vt_records,
    }


def analyze_age_bands(start_date=None, end_date=None, db_path_override=None):
    """
    Analyzes non-identifying patient age bands using aggregated operational data:
    - Total patients registered in each age band
    - Total visits generated by each age band & share of total visits (%)
    - Average visits per patient within each age band
    - Top utilized department for each age band
    - Cross-tabulation matrix (Age Band x Department)
    """
    df_patients, _, _, df_merged = load_operational_dataframes(
        start_date=start_date, end_date=end_date, db_path_override=db_path_override
    )

    if df_merged.empty:
        return {
            "disclaimer": Config.OPERATIONAL_DISCLAIMER,
            "age_band_summary": [],
            "age_department_matrix": []
        }

    total_visits = int(len(df_merged))
    total_registered_patients = int(len(df_patients)) if not df_patients.empty else 0

    # Patient counts per age band from master patients table
    pat_band_counts = df_patients.groupby("age_band")["patient_id"].count().to_dict() if not df_patients.empty else {}

    # Visit aggregations per age band
    band_order = list(Config.VALID_AGE_BANDS)
    age_records = []
    for band in band_order:
        sub = df_merged[df_merged["age_band"] == band]
        v_count = int(len(sub))
        u_active = int(sub["patient_id"].nunique()) if not sub.empty else 0
        reg_pats = int(pat_band_counts.get(band, u_active))
        share_pct = float(np.round((v_count / total_visits) * 100.0, 2)) if total_visits > 0 else 0.0
        v_per_active = float(np.round(v_count / u_active, 2)) if u_active > 0 else 0.0

        if not sub.empty:
            top_dept_series = sub.groupby("department_name")["visit_id"].count().sort_values(ascending=False)
            top_dept = str(top_dept_series.index[0])
            top_dept_visits = int(top_dept_series.iloc[0])
        else:
            top_dept = "N/A"
            top_dept_visits = 0

        age_records.append({
            "age_band": band,
            "registered_patients": reg_pats,
            "active_patients_in_period": u_active,
            "total_visits": v_count,
            "visit_share_pct": share_pct,
            "mean_visits_per_active_patient": v_per_active,
            "primary_department": top_dept,
            "primary_department_visits": top_dept_visits,
        })

    # Cross-tabulation: Age Band x Department Name
    ctab = pd.crosstab(df_merged["age_band"], df_merged["department_name"]).reindex(band_order, fill_value=0)
    matrix_records = []
    for band, row in ctab.iterrows():
        entry = {"age_band": str(band)}
        for dept_name, val in row.items():
            entry[str(dept_name)] = int(val)
        entry["row_total"] = int(row.sum())
        matrix_records.append(entry)

    return {
        "disclaimer": Config.OPERATIONAL_DISCLAIMER,
        "total_registered_patients": total_registered_patients,
        "total_visits_analyzed": total_visits,
        "age_band_summary": age_records,
        "age_department_matrix": matrix_records,
    }
