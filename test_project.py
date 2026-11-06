"""
Deliverable D6: Automated Test Suite
Hospital Patient Data Analysis System (Project 7)

Covers all 5 mandatory testing categories specified in D6:
1. Normal Input: Valid CRUD operations, valid analytics queries, accurate totals & shares, chart generation
2. Invalid Input: Malformed dates, invalid age bands, PII field rejection, clinical diagnosis field rejection, unauthorized access rejection
3. Empty Datasets: Behavior of analytics and API routes when visits table is empty or date filter matches zero records
4. Boundary Values: Single-day filter (start_date == end_date), inverted date ranges (start_date > end_date), min/max age band boundaries ('0-17', '65+'), department name length limits
5. Database Errors: Foreign key constraint violations (non-existent patient_id or department_id), duplicate department names, unreachable database file paths
"""
import os
import json
import tempfile
import unittest
from config import Config
from db import init_sqlite_from_sql_file, execute_query, DatabaseError
from app import app


class HospitalAnalyticsTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="hospital_test_")
        cls.test_db = os.path.join(cls.temp_dir, "test_hospital.db")
        sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema_and_seed.sql")
        init_sqlite_from_sql_file(sql_file_path=sql_path, db_path_override=cls.test_db)
        app.config["DB_PATH_OVERRIDE"] = cls.test_db
        cls.client = app.test_client()
        cls.auth_headers = {"X-Analyst-Token": Config.ANALYST_API_TOKEN}

    # =========================================================================
    # Category 1: Normal Input & Core Workflows
    # =========================================================================
    def test_01_normal_health_check_and_seed_counts(self):
        """TC-01 [Normal Input]: Verify health endpoint and seeded record counts (7 depts, 120 patients, 420 visits)."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["records_summary"]["departments"], 7)
        self.assertEqual(data["records_summary"]["deidentified_patients"], 120)
        self.assertEqual(data["records_summary"]["hospital_visits"], 420)
        self.assertIn("OPERATIONAL STATISTICS ONLY", data["disclaimer"])

    def test_02_normal_create_patient_and_visit_crud(self):
        """TC-02 [Normal Input]: Create a de-identified patient, log a visit, update visit_type, and delete visit."""
        # Create patient
        p_resp = self.client.post(
            "/api/patients",
            json={"age_band": "35-49", "gender_optional": "Female"},
            headers=self.auth_headers
        )
        self.assertEqual(p_resp.status_code, 201)
        new_pid = p_resp.get_json()["patient"]["patient_id"]

        # Create visit
        v_resp = self.client.post(
            "/api/visits",
            json={"patient_id": new_pid, "department_id": 2, "visit_date": "2026-10-15", "visit_type": "Outpatient"},
            headers=self.auth_headers
        )
        self.assertEqual(v_resp.status_code, 201)
        vid = v_resp.get_json()["visit"]["visit_id"]

        # Update visit
        u_resp = self.client.put(
            f"/api/visits/{vid}",
            json={"visit_type": "Follow-up", "visit_date": "2026-10-16"},
            headers=self.auth_headers
        )
        self.assertEqual(u_resp.status_code, 200)
        self.assertEqual(u_resp.get_json()["visit"]["visit_type"], "Follow-up")

        # Delete visit to restore exact seed count of 420 visits
        d_resp = self.client.delete(f"/api/visits/{vid}", headers=self.auth_headers)
        self.assertEqual(d_resp.status_code, 200)

    def test_03_normal_department_workload_reconciliation(self):
        """TC-03 [Normal Input]: Verify department workload totals reconcile to 420 visits and 100% share."""
        resp = self.client.get("/api/analytics/department-workload")
        self.assertEqual(resp.status_code, 200)
        report = resp.get_json()["data"]
        self.assertEqual(report["total_hospital_visits"], 420)
        sum_dept_visits = sum(d["total_visits"] for d in report["departments"])
        sum_shares = sum(d["workload_share_pct"] for d in report["departments"])
        self.assertEqual(sum_dept_visits, 420)
        self.assertAlmostEqual(sum_shares, 100.0, places=1)

    def test_04_normal_visit_trends_and_age_bands(self):
        """TC-04 [Normal Input]: Verify monthly visit trends (10 months) and age-band cross-tabulation totals."""
        t_resp = self.client.get("/api/analytics/visit-trends")
        self.assertEqual(t_resp.status_code, 200)
        t_data = t_resp.get_json()["data"]
        self.assertEqual(len(t_data["monthly_trends"]), 10)
        self.assertEqual(sum(m["total_visits"] for m in t_data["monthly_trends"]), 420)

        a_resp = self.client.get("/api/analytics/age-bands")
        self.assertEqual(a_resp.status_code, 200)
        a_data = a_resp.get_json()["data"]
        self.assertEqual(len(a_data["age_band_summary"]), 5)
        self.assertEqual(sum(a["total_visits"] for a in a_data["age_band_summary"]), 420)

    def test_05_normal_chart_generation_and_serving(self):
        """TC-05 [Normal Input]: Trigger Matplotlib chart generation and retrieve PNG image bytes."""
        g_resp = self.client.post("/api/charts/generate")
        self.assertEqual(g_resp.status_code, 200)
        charts = g_resp.get_json()["generated_charts"]
        self.assertEqual(len(charts), 4)

        img_resp = self.client.get("/api/charts/department_workload")
        self.assertEqual(img_resp.status_code, 200)
        self.assertTrue(len(img_resp.data) > 5000)

    # =========================================================================
    # Category 2: Invalid Input & Access / Scope Enforcement
    # =========================================================================
    def test_06_invalid_unauthorized_record_access_blocked(self):
        """TC-06 [Invalid Input / Security]: Verify raw patient/visit endpoints reject requests without X-Analyst-Token."""
        r1 = self.client.get("/api/patients")
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r1.get_json()["error_code"], "ACCESS_RESTRICTED")

        r2 = self.client.get("/api/visits")
        self.assertEqual(r2.status_code, 403)

    def test_07_invalid_pii_and_clinical_fields_rejected(self):
        """TC-07 [Invalid Input / Privacy Scope]: Reject patient PII (name, phone) and visit clinical diagnoses."""
        pii_resp = self.client.post(
            "/api/patients",
            json={"age_band": "18-34", "patient_name": "Rahul Sharma", "phone": "9876543210"},
            headers=self.auth_headers
        )
        self.assertEqual(pii_resp.status_code, 400)
        self.assertEqual(pii_resp.get_json()["error_code"], "PRIVACY_BOUNDARY_VIOLATION")

        clin_resp = self.client.post(
            "/api/visits",
            json={"patient_id": 1, "department_id": 1, "visit_date": "2026-05-10", "diagnosis": "Hypertension"},
            headers=self.auth_headers
        )
        self.assertEqual(clin_resp.status_code, 400)
        self.assertEqual(clin_resp.get_json()["error_code"], "CLINICAL_SCOPE_VIOLATION")

    def test_08_invalid_age_band_visit_type_and_date_format(self):
        """TC-08 [Invalid Input]: Reject unsupported age_band ('20-30'), invalid visit_type ('Surgery'), and bad dates ('2026-02-30')."""
        r_age = self.client.post(
            "/api/patients",
            json={"age_band": "20-30", "gender_optional": "Male"},
            headers=self.auth_headers
        )
        self.assertEqual(r_age.status_code, 400)

        r_type = self.client.post(
            "/api/visits",
            json={"patient_id": 1, "department_id": 1, "visit_date": "2026-05-10", "visit_type": "Surgery"},
            headers=self.auth_headers
        )
        self.assertEqual(r_type.status_code, 400)

        r_date = self.client.post(
            "/api/visits",
            json={"patient_id": 1, "department_id": 1, "visit_date": "2026-02-30", "visit_type": "Outpatient"},
            headers=self.auth_headers
        )
        self.assertEqual(r_date.status_code, 400)

    # =========================================================================
    # Category 3: Empty Datasets Handling
    # =========================================================================
    def test_09_empty_dataset_filter_window(self):
        """TC-09 [Empty Dataset]: Verify analytics endpoints gracefully handle a date range with 0 visits (2025-01-01 to 2025-01-31)."""
        w_resp = self.client.get("/api/analytics/department-workload?start_date=2025-01-01&end_date=2025-01-31")
        self.assertEqual(w_resp.status_code, 200)
        w_data = w_resp.get_json()["data"]
        self.assertEqual(w_data["total_hospital_visits"], 0)
        self.assertEqual(w_data["departments"], [])

        t_resp = self.client.get("/api/analytics/visit-trends?start_date=2025-01-01&end_date=2025-01-31")
        self.assertEqual(t_resp.status_code, 200)
        self.assertEqual(t_resp.get_json()["data"]["monthly_trends"], [])

    def test_10_empty_database_tables(self):
        """TC-10 [Empty Dataset]: Verify analytics on a newly initialized database with 0 visits and 0 patients."""
        empty_db = os.path.join(self.temp_dir, "empty_hospital.db")
        init_sqlite_from_sql_file(db_path_override=empty_db)
        execute_query("DELETE FROM visits", fetch=False, db_path_override=empty_db)
        execute_query("DELETE FROM patients", fetch=False, db_path_override=empty_db)

        app.config["DB_PATH_OVERRIDE"] = empty_db
        try:
            resp = self.client.get("/api/analytics/age-bands")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["data"]["age_band_summary"], [])
        finally:
            app.config["DB_PATH_OVERRIDE"] = self.test_db

    # =========================================================================
    # Category 4: Boundary Values
    # =========================================================================
    def test_11_boundary_single_day_and_inverted_date_range(self):
        """TC-11 [Boundary Values]: Single-day filter (start_date == end_date) succeeds; inverted range (start > end) returns 400."""
        single_resp = self.client.get(
            "/api/visits?start_date=2026-08-15&end_date=2026-08-15",
            headers=self.auth_headers
        )
        self.assertEqual(single_resp.status_code, 200)

        inv_resp = self.client.get(
            "/api/visits?start_date=2026-09-10&end_date=2026-09-01",
            headers=self.auth_headers
        )
        self.assertEqual(inv_resp.status_code, 400)

    def test_12_boundary_department_name_lengths_and_extreme_age_bands(self):
        """TC-12 [Boundary Values]: Test empty department name (0 chars), >100 chars rejection, and extreme age bands ('0-17', '65+')."""
        empty_dept = self.client.post("/api/departments", json={"department_name": "   "}, headers=self.auth_headers)
        self.assertEqual(empty_dept.status_code, 400)

        long_dept = self.client.post("/api/departments", json={"department_name": "D" * 101}, headers=self.auth_headers)
        self.assertEqual(long_dept.status_code, 400)

        b_young = self.client. get("/api/patients?age_band=0-17", headers=self.auth_headers)
        self.assertEqual(b_young.status_code, 200)
        self.assertTrue(b_young.get_json()["count"] > 0)

        b_senior = self.client.get("/api/patients?age_band=65%2B", headers=self.auth_headers)
        self.assertEqual(b_senior.status_code, 200)
        self.assertTrue(b_senior.get_json()["count"] > 0)

    # =========================================================================
    # Category 5: Database Constraints & Error Handling
    # =========================================================================
    def test_13_db_error_foreign_key_and_duplicate_department(self):
        """TC-13 [Database Errors]: Non-existent patient_id/department_id returns 404; duplicate department returns 400."""
        fk_pat = self.client.post(
            "/api/visits",
            json={"patient_id": 99999, "department_id": 1, "visit_date": "2026-06-01", "visit_type": "Outpatient"},
            headers=self.auth_headers
        )
        self.assertEqual(fk_pat.status_code, 404)
        self.assertEqual(fk_pat.get_json()["error_code"], "FOREIGN_KEY_ERROR")

        fk_dept = self.client.post(
            "/api/visits",
            json={"patient_id": 1, "department_id": 888, "visit_date": "2026-06-01", "visit_type": "Outpatient"},
            headers=self.auth_headers
        )
        self.assertEqual(fk_dept.status_code, 404)

        dup_dept = self.client.post(
            "/api/departments",
            json={"department_name": "Cardiology"},
            headers=self.auth_headers
        )
        self.assertEqual(dup_dept.status_code, 400)
        self.assertEqual(dup_dept.get_json()["error_code"], "DUPLICATE_OR_DB_ERROR")

    def test_14_db_error_unreachable_database_path(self):
        """TC-14 [Database Errors]: Simulate database connection failure via invalid path and verify 500 error handling."""
        app.config["DB_PATH_OVERRIDE"] = "/non_existent_dir_xyz/unreachable.db"
        try:
            resp = self.client.get("/api/health")
            self.assertEqual(resp.status_code, 500)
            self.assertEqual(resp.get_json()["error_code"], "DATABASE_ERROR")
        finally:
            app.config["DB_PATH_OVERRIDE"] = self.test_db


if __name__ == "__main__":
    unittest.main(verbosity=2)
