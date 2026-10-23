from datetime import date
from decimal import Decimal
from rest_framework.test import APITestCase
from . import models as m

class AccessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        y = m.AcademicYear.objects.create(name="2026-27", start_date=date(2026, 4, 1),
                                          end_date=date(2027, 3, 31), is_current=True)
        cls.teacher = m.User.objects.create_user("t1", password="x" * 12, role="teacher")
        cls.other_teacher = m.User.objects.create_user("t2", password="x" * 12, role="teacher")
        cls.sec = m.ClassSection.objects.create(academic_year=y, grade_level=5, name="A",
                                                class_teacher=cls.teacher)
        cls.maths = m.Subject.objects.create(code="MA", name="Maths")
        m.TeachingAssignment.objects.create(teacher=cls.teacher, section=cls.sec, subject=cls.maths)
        mk = lambda n, u=None: m.Student.objects.create(
            user=u, admission_no=n, first_name=n, date_of_birth=date(2015, 1, 1), gender="M")
        cls.su = m.User.objects.create_user("s1", password="x" * 12, role="student")
        cls.s1, cls.s2 = mk("A1", cls.su), mk("A2")
        for s in (cls.s1, cls.s2):
            m.Enrollment.objects.create(student=s, section=cls.sec)
        cls.parent = m.User.objects.create_user("p1", password="x" * 12, role="parent")
        m.Guardian.objects.create(user=cls.parent).students.add(cls.s1)
        cls.a = m.Assessment.objects.create(section=cls.sec, subject=cls.maths, name="Unit 1",
                                            max_marks=50, weight=1, date=date(2026, 8, 1))

    def test_student_sees_only_self(self):
        self.client.force_authenticate(self.su)
        ids = [r["id"] for r in self.client.get("/api/students/").data["results"]]
        self.assertEqual(ids, [self.s1.id])

    def test_parent_sees_only_own_child(self):
        self.client.force_authenticate(self.parent)
        ids = [r["id"] for r in self.client.get("/api/students/").data["results"]]
        self.assertEqual(ids, [self.s1.id])

    def test_student_cannot_write(self):
        self.client.force_authenticate(self.su)
        self.assertEqual(self.client.post("/api/students/", {}).status_code, 403)

    def test_unassigned_teacher_cannot_enter_grades(self):
        self.client.force_authenticate(self.other_teacher)
        r = self.client.post(f"/api/assessments/{self.a.id}/grades/",
                             [{"student": self.s1.id, "marks": "40"}], format="json")
        self.assertIn(r.status_code, (403, 404))

    def test_grade_entry_and_report_card_and_audit(self):
        self.client.force_authenticate(self.teacher)
        r = self.client.post(f"/api/assessments/{self.a.id}/grades/",
                             [{"student": self.s1.id, "marks": "40"}], format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(m.AuditLog.objects.filter(model="Grade", user=self.teacher).exists())
        self.client.force_authenticate(self.parent)
        card = self.client.get(f"/api/students/{self.s1.id}/report-card/").data
        self.assertEqual(Decimal(str(card["overall_percentage"])), Decimal("80"))
        self.assertEqual(card["overall_grade"], "A")

    def test_marks_over_max_rejected(self):
        self.client.force_authenticate(self.teacher)
        r = self.client.post(f"/api/assessments/{self.a.id}/grades/",
                             [{"student": self.s1.id, "marks": "51"}], format="json")
        self.assertEqual(r.status_code, 400)
