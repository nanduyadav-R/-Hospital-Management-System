import sqlite3
import re
import os

db_path = 'hospital_analytics.db'
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 1. Schema
cur.executescript('''
CREATE TABLE IF NOT EXISTS departments (
    department_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    department_name TEXT NOT NULL UNIQUE,
    description     TEXT,
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
    FOREIGN KEY (patient_id)    REFERENCES patients(patient_id),
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE VIEW IF NOT EXISTS vw_monthly_visits AS
SELECT
    strftime('%Y-%m', visit_date) AS year_month,
    COUNT(*) AS total_visits
FROM visits
GROUP BY year_month
ORDER BY year_month;

CREATE VIEW IF NOT EXISTS vw_dept_workload AS
SELECT
    d.department_name,
    COUNT(v.visit_id) AS total_visits,
    COUNT(DISTINCT v.patient_id) AS unique_patients,
    SUM(CASE WHEN v.visit_type='Emergency' THEN 1 ELSE 0 END) AS emergency_visits
FROM departments d
LEFT JOIN visits v ON d.department_id = v.department_id
GROUP BY d.department_id, d.department_name
ORDER BY total_visits DESC;

CREATE VIEW IF NOT EXISTS vw_age_band_summary AS
SELECT
    p.age_band,
    COUNT(v.visit_id) AS total_visits,
    COUNT(DISTINCT p.patient_id) AS unique_patients
FROM patients p
LEFT JOIN visits v ON p.patient_id = v.patient_id
GROUP BY p.age_band;
''')

# 2. Departments
departments = [
    ('Cardiology', 'Heart and cardiovascular system'),
    ('Orthopedics', 'Bones, joints and musculoskeletal'),
    ('Neurology', 'Brain, spinal cord and nervous system'),
    ('Pediatrics', 'Children and adolescents'),
    ('General Medicine', 'General consultations and primary care'),
    ('Dermatology', 'Skin conditions'),
    ('Oncology', 'Cancer screening and treatment support'),
    ('Emergency', 'Acute and emergency care'),
    ('Gynecology', "Women's reproductive health"),
    ('ENT', 'Ear, nose and throat')
]
cur.executemany('INSERT INTO departments (department_name, description) VALUES (?, ?)', departments)

# 3. Patients
patients = [
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','M'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','F'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','Other'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('65+','F'),('50-64','M'),('18-34','F'),('35-49','M'),('65+','F'),
    ('18-34','M'),('50-64','F'),('35-49','M'),('0-17','F'),('65+','M'),
    ('18-34','F'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('50-64','M'),('18-34','F'),('65+','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','F'),('35-49','M'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('50-64','M'),('18-34','F'),('65+','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','F'),('35-49','M'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('65+','F'),('50-64','M'),('18-34','F'),('35-49','M'),('65+','F'),
    ('18-34','M'),('50-64','F'),('35-49','M'),('0-17','F'),('65+','M'),
    ('18-34','F'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F'),
    ('18-34','F'),('65+','M'),('50-64','F'),('35-49','M'),('0-17','M'),
    ('18-34','M'),('65+','F'),('50-64','M'),('35-49','F'),('0-17','F')
]
cur.executemany('INSERT INTO patients (age_band, gender) VALUES (?, ?)', patients)

# 4. Visits from schema.sql
with open('sql/schema.sql', 'r', encoding='utf-8') as f:
    sql_text = f.read()

visit_pattern = re.compile(r"\((\d+),\s*(\d+),\s*'([^']+)',\s*'([^']+)'\)")
visits = [(int(m[0]), int(m[1]), m[2], m[3]) for m in visit_pattern.findall(sql_text)]
cur.executemany('INSERT INTO visits (patient_id, department_id, visit_date, visit_type) VALUES (?, ?, ?, ?)', visits)

conn.commit()
d_cnt = cur.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
p_cnt = cur.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
v_cnt = cur.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
print(f"DATABASE INITIALIZED SUCCESSFULLY!")
print(f"Departments: {d_cnt}")
print(f"Patients:    {p_cnt}")
print(f"Visits:      {v_cnt}")
conn.close()
