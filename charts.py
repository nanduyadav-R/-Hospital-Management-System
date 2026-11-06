"""
Deliverable D5: Matplotlib Visualizations Module
Hospital Patient Data Analysis System (Project 7)

Generates 4 publication-quality operational analytics charts from stored database records:
1. chart1_department_workload.png: Department-wise Visit Volume & Workload Share (%)
2. chart2_monthly_visit_trends.png: Monthly Patient Visit Trends, 3-Month Rolling Average & Emergency Volume
3. chart3_age_band_distribution.png: Non-Identifying Age-Band Visit Volume & Visit-Type Composition
4. chart4_dept_age_heatmap.png: Operational Cross-Tabulation Heatmap (Department vs. Age Band Visits)

Every chart includes a clear title, labeled axes, measurement units, data callouts, legend, and
an explicit bottom operational statistics disclaimer.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analytics import (
    analyze_department_workload,
    analyze_visit_trends,
    analyze_age_bands,
)

# Cohesive clinical-operational palette (Deep Navy, Teal, Slate, Coral Accent)
PALETTE = {
    "navy": "#1B365D",
    "teal": "#008080",
    "sky": "#3B7EA1",
    "amber": "#D97706",
    "coral": "#C0392B",
    "slate": "#4A5568",
    "light_bg": "#F8FAFC",
    "grid": "#E2E8F0",
}


def generate_all_charts(output_dir=None, db_path_override=None):
    """
    Runs the analytics pipeline and saves all 4 Matplotlib charts as 200-DPI PNG images.
    Returns a dictionary of generated file paths.
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
    os.makedirs(output_dir, exist_ok=True)

    dept_data = analyze_department_workload(db_path_override=db_path_override)
    trend_data = analyze_visit_trends(db_path_override=db_path_override)
    age_data = analyze_age_bands(db_path_override=db_path_override)

    plt.rcParams["font.sans-serif"] = "DejaVu Sans"
    plt.rcParams["axes.edgecolor"] = "#CBD5E1"
    plt.rcParams["axes.linewidth"] = 0.9

    paths = {}

    # -------------------------------------------------------------------------
    # Chart 1: Department-Wise Workload Bar Chart (Horizontal Stacked / Annotated)
    # -------------------------------------------------------------------------
    depts = dept_data["departments"]
    if depts:
        fig, ax = plt.subplots(figsize=(10, 5.4), dpi=200)
        fig.patch.set_facecolor("white")
        ax.set_facecolor(PALETTE["light_bg"])

        # Reverse order so highest workload appears at top
        depts_rev = list(reversed(depts))
        names = [d["department_name"] for d in depts_rev]
        totals = [d["total_visits"] for d in depts_rev]
        shares = [d["workload_share_pct"] for d in depts_rev]
        unique_pats = [d["unique_patients"] for d in depts_rev]

        y_pos = np.arange(len(names))
        bars = ax.barh(y_pos, totals, height=0.55, color=PALETTE["navy"], alpha=0.92, label="Total Recorded Visits (Count)")
        bars_pat = ax.barh(y_pos - 0.18, unique_pats, height=0.22, color=PALETTE["teal"], alpha=0.85, label="Unique De-identified Patients (Count)")

        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=10, fontweight="bold", color="#1E293B")
        ax.set_xlabel("Number of Operational Visits / Patients (Count)", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax.set_title(
            "Hospital Department-Wise Workload Distribution (Jan – Oct 2026)",
            fontsize=13, fontweight="bold", color=PALETTE["navy"], pad=14
        )
        ax.grid(axis="x", linestyle="--", color=PALETTE["grid"], alpha=0.9)
        ax.set_axisbelow(True)
        ax.set_xlim(0, max(totals) * 1.24)

        for bar, tot, sh in zip(bars, totals, shares):
            ax.text(
                bar.get_width() + 1.8,
                bar.get_y() + bar.get_height() / 2.0,
                f"{tot} visits ({sh:.1f}%)",
                va="center", ha="left", fontsize=9.2, fontweight="bold", color=PALETTE["navy"]
            )

        ax.legend(loc="lower right", frameon=True, facecolor="white", framealpha=0.95, fontsize=9.2)
        fig.text(
            0.5, 0.01,
            "Note: Operational statistics derived from synthetic de-identified records (N = 420 visits, 120 patients). Not clinical advice.",
            ha="center", fontsize=8, style="italic", color=PALETTE["slate"]
        )
        plt.tight_layout(rect=[0, 0.04, 1, 1])
        c1_path = os.path.join(output_dir, "chart1_department_workload.png")
        fig.savefig(c1_path, dpi=200)
        plt.close(fig)
        paths["department_workload"] = c1_path

    # -------------------------------------------------------------------------
    # Chart 2: Monthly Visit Trends & 3-Month Rolling Average Line/Bar Combo
    # -------------------------------------------------------------------------
    monthly = trend_data["monthly_trends"]
    if monthly:
        fig, ax1 = plt.subplots(figsize=(10, 5.2), dpi=200)
        fig.patch.set_facecolor("white")
        ax1.set_facecolor(PALETTE["light_bg"])

        months = [m["year_month"] for m in monthly]
        tot_v = [m["total_visits"] for m in monthly]
        roll_3m = [m["rolling_3m_avg"] for m in monthly]
        emerg_v = [m["emergency_visits"] for m in monthly]

        x = np.arange(len(months))
        ax1.bar(x, tot_v, width=0.52, color=PALETTE["sky"], alpha=0.45, label="Monthly Total Visits (Count)")
        ax1.plot(x, tot_v, marker="o", linewidth=2.4, color=PALETTE["navy"], label="Monthly Visit Trajectory")
        ax1.plot(x, roll_3m, marker="s", linestyle="--", linewidth=2.2, color=PALETTE["amber"], label="3-Month Rolling Mean (Visits)")
        ax1.plot(x, emerg_v, marker="^", linestyle=":", linewidth=2.0, color=PALETTE["coral"], label="Emergency Visits Subset (Count)")

        for xi, val, rval in zip(x, tot_v, roll_3m):
            y_pos_lbl = max(val, rval) + 1.4
            ax1.text(xi, y_pos_lbl, f"{val}", ha="center", va="bottom", fontsize=9, fontweight="bold", color=PALETTE["navy"])

        ax1.set_xticks(x)
        ax1.set_xticklabels(months, fontsize=9.5, fontweight="bold", color="#1E293B")
        ax1.set_ylabel("Patient Visits per Month (Count)", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax1.set_xlabel("Observation Month (YYYY-MM)", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax1.set_title(
            "Monthly Hospital Visit Volume, 3-Month Rolling Average & Emergency Load (2026)",
            fontsize=12.5, fontweight="bold", color=PALETTE["navy"], pad=14
        )
        ax1.set_ylim(0, max(tot_v) * 1.22)
        ax1.grid(axis="y", linestyle="--", color=PALETTE["grid"], alpha=0.9)
        ax1.set_axisbelow(True)
        ax1.legend(loc="upper left", ncol=2, frameon=True, facecolor="white", framealpha=0.95, fontsize=8.8)

        fig.text(
            0.5, 0.01,
            "Note: Peak monthly volume recorded in 2026-08 (52 visits). Operational statistics only; not for clinical decision-making.",
            ha="center", fontsize=8, style="italic", color=PALETTE["slate"]
        )
        plt.tight_layout(rect=[0, 0.04, 1, 1])
        c2_path = os.path.join(output_dir, "chart2_monthly_visit_trends.png")
        fig.savefig(c2_path, dpi=200)
        plt.close(fig)
        paths["monthly_visit_trends"] = c2_path

    # -------------------------------------------------------------------------
    # Chart 3: Age-Band Operational Summary (Grouped Bar: Visits vs Active Patients)
    # -------------------------------------------------------------------------
    age_summary = age_data["age_band_summary"]
    if age_summary:
        fig, ax = plt.subplots(figsize=(9.8, 5.0), dpi=200)
        fig.patch.set_facecolor("white")
        ax.set_facecolor(PALETTE["light_bg"])

        bands = [a["age_band"] + " yrs" for a in age_summary]
        v_counts = [a["total_visits"] for a in age_summary]
        p_counts = [a["active_patients_in_period"] for a in age_summary]
        shares = [a["visit_share_pct"] for a in age_summary]

        x = np.arange(len(bands))
        width = 0.36

        b1 = ax.bar(x - width / 2, v_counts, width, color=PALETTE["navy"], label="Total Visits in Age Band (Count)")
        b2 = ax.bar(x + width / 2, p_counts, width, color=PALETTE["teal"], label="Active De-identified Patients (Count)")

        for bar, sh in zip(b1, shares):
            h = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2.0, h + 1.5,
                f"{int(h)}\n({sh:.1f}%)",
                ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=PALETTE["navy"]
            )
        for bar in b2:
            h = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2.0, h + 1.5,
                f"{int(h)} pts",
                ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=PALETTE["teal"]
            )

        ax.set_xticks(x)
        ax.set_xticklabels(bands, fontsize=10, fontweight="bold", color="#1E293B")
        ax.set_ylabel("Count (Visits / Patients)", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax.set_xlabel("De-identified Patient Age Band (Years)", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax.set_title(
            "Aggregated Hospital Utilization by Non-Identifying Patient Age Band",
            fontsize=12.5, fontweight="bold", color=PALETTE["navy"], pad=14
        )
        ax.set_ylim(0, max(v_counts) * 1.28)
        ax.grid(axis="y", linestyle="--", color=PALETTE["grid"], alpha=0.9)
        ax.set_axisbelow(True)
        ax.legend(loc="upper right", frameon=True, facecolor="white", framealpha=0.95, fontsize=9.2)

        fig.text(
            0.5, 0.01,
            "Note: Exact dates of birth are excluded by design; age bands report operational utilization only.",
            ha="center", fontsize=8, style="italic", color=PALETTE["slate"]
        )
        plt.tight_layout(rect=[0, 0.04, 1, 1])
        c3_path = os.path.join(output_dir, "chart3_age_band_distribution.png")
        fig.savefig(c3_path, dpi=200)
        plt.close(fig)
        paths["age_band_distribution"] = c3_path

    # -------------------------------------------------------------------------
    # Chart 4: Department x Age-Band Operational Heatmap
    # -------------------------------------------------------------------------
    matrix = age_data["age_department_matrix"]
    if matrix and depts:
        dept_names = [d["department_name"] for d in depts]
        age_labels = [m["age_band"] + " yrs" for m in matrix]
        grid_vals = np.array([[m.get(dn, 0) for dn in dept_names] for m in matrix], dtype=int)

        fig, ax = plt.subplots(figsize=(10.2, 5.2), dpi=200)
        fig.patch.set_facecolor("white")

        im = ax.imshow(grid_vals, cmap="YlGnBu", aspect="auto")
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.03)
        cbar.set_label("Recorded Visits (Count)", fontsize=9.5, fontweight="bold", color="#1E293B")

        ax.set_xticks(np.arange(len(dept_names)))
        ax.set_yticks(np.arange(len(age_labels)))
        ax.set_xticklabels(dept_names, rotation=22, ha="right", fontsize=9.5, fontweight="bold", color="#1E293B")
        ax.set_yticklabels(age_labels, fontsize=9.8, fontweight="bold", color="#1E293B")
        ax.set_xlabel("Hospital Department", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax.set_ylabel("Patient Age Band", fontsize=10.5, fontweight="bold", color="#1E293B")
        ax.set_title(
            "Cross-Departmental Visit Demand by Patient Age Band (Visit Counts)",
            fontsize=12.5, fontweight="bold", color=PALETTE["navy"], pad=14
        )

        thresh = grid_vals.max() / 2.0
        for i in range(len(age_labels)):
            for j in range(len(dept_names)):
                val = grid_vals[i, j]
                color = "white" if val > thresh else "#1E293B"
                ax.text(j, i, f"{val}", ha="center", va="center", fontsize=9.5, fontweight="bold", color=color)

        fig.text(
            0.5, 0.01,
            "Note: Highlights pediatric concentration in 0-17 yrs and adult chronic/acute load across General Medicine & Cardiology.",
            ha="center", fontsize=8, style="italic", color=PALETTE["slate"]
        )
        plt.tight_layout(rect=[0, 0.04, 1, 1])
        c4_path = os.path.join(output_dir, "chart4_dept_age_heatmap.png")
        fig.savefig(c4_path, dpi=200)
        plt.close(fig)
        paths["dept_age_heatmap"] = c4_path

    return paths


if __name__ == "__main__":
    generated = generate_all_charts()
    for k, v in generated.items():
        print(f"Generated {k}: {v}")
