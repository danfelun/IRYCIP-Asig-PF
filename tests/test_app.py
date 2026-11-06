import os
import tempfile
import unittest
from openpyxl import Workbook
from app import create_app
from app.db import import_students_xlsx, connect_db
from app.topics import SPECIAL_TOPIC_CODE


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.xlsx = os.path.join(self.tmp.name, "students.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(["Nombre", "Correo Institucional", "Grupo"])
        for g in range(1, 13):
            ws.append([f"Estudiante {g}", f"g{g}@example.edu", g])
        wb.save(self.xlsx)
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": self.db_path,
            "STUDENTS_XLSX": "",
            "ADMIN_EMAIL": "admin@example.edu",
            "ADMIN_PASSWORD": "secret",
            "ASSIGNMENT_OVERRIDES": "10:G10-FIXED",
        })
        import_students_xlsx(self.xlsx, self.db_path)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def login_and_draw(self, group):
        self.client.post("/login", data={"email": f"g{group}@example.edu"})
        return self.client.post("/asignacion/sortear", follow_redirects=True)

    def test_group10_is_fixed(self):
        self.login_and_draw(10)
        db = connect_db(self.db_path)
        row = db.execute("select topic_code from assignments where group_no=10").fetchone()
        db.close()
        self.assertEqual(row["topic_code"], SPECIAL_TOPIC_CODE)

    def test_other_groups_unique_while_unused_topics_exist(self):
        for g in [1, 2, 3, 4, 5]:
            self.client.post("/logout")
            self.login_and_draw(g)
        db = connect_db(self.db_path)
        rows = db.execute("select topic_code from assignments").fetchall()
        db.close()
        codes = [r["topic_code"] for r in rows]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn(SPECIAL_TOPIC_CODE, codes)

    def test_second_member_cannot_redraw(self):
        db = connect_db(self.db_path)
        db.execute(
            "insert into students(email,name,group_no,active) values(?,?,?,1)",
            ("second@example.edu", "Second", 1),
        )
        db.close()
        self.login_and_draw(1)
        db = connect_db(self.db_path)
        first = db.execute("select topic_code from assignments where group_no=1").fetchone()["topic_code"]
        db.close()
        self.client.post("/logout")
        self.client.post("/login", data={"email": "second@example.edu"})
        self.client.post("/asignacion/sortear")
        db = connect_db(self.db_path)
        second = db.execute("select topic_code from assignments where group_no=1").fetchone()["topic_code"]
        db.close()
        self.assertEqual(first, second)

    def test_groups_are_dynamic_and_can_exceed_12(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Nombre", "Correo Institucional", "Grupo"])
        for g in range(1, 15):
            ws.append([f"Alumno {g}", f"a{g}@example.edu", g])
        wb.save(self.xlsx)
        import_students_xlsx(self.xlsx, self.db_path)

        self.client.post("/admin/login", data={"email": "admin@example.edu", "password": "secret"})
        response = self.client.get("/admin/api/status")
        data = response.get_json()
        self.assertEqual(data["total_groups"], 14)
        self.assertEqual([g["group_no"] for g in data["groups"]], list(range(1, 15)))

    def test_admin_session_survives_student_login_and_refresh(self):
        self.client.post("/admin/login", data={"email": "admin@example.edu", "password": "secret"})
        self.client.post("/login", data={"email": "g1@example.edu"})
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"PANEL DOCENTE", response.data)

    def test_sync_marks_removed_students_inactive(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Nombre", "Correo Institucional", "Grupo"])
        ws.append(["Solo Uno", "solo@example.edu", 1])
        wb.save(self.xlsx)
        import_students_xlsx(self.xlsx, self.db_path)
        db = connect_db(self.db_path)
        active = db.execute("select count(*) c from students where active=1").fetchone()["c"]
        db.close()
        self.assertEqual(active, 1)


if __name__ == "__main__":
    unittest.main()
