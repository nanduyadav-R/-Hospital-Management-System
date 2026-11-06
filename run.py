"""
Entry point for the Hospital Patient Data Analysis System.
Usage:
    py run.py             — starts Flask dev server
    py run.py --analysis  — runs analysis report only
    py run.py --charts    — generates all charts
    py run.py --all       — analysis + charts + Flask server
"""
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app

app = create_app()


def run_analysis():
    from analysis.analysis import print_report
    print_report()


def run_charts():
    from analysis.visualizations import generate_all_charts
    generate_all_charts()


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--analysis" in args:
        run_analysis()
    elif "--charts" in args:
        run_charts()
    elif "--all" in args:
        run_analysis()
        run_charts()
        app.run(host="0.0.0.0", port=5000, debug=True)
    else:
        print("Starting Hospital Analytics Flask server on http://127.0.0.1:5000")
        app.run(host="0.0.0.0", port=5000, debug=True)
