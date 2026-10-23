from django.contrib.auth.models import AbstractUser
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        PRINCIPAL = "principal", "Principal"
        TEACHER = "teacher", "Teacher"
        ACCOUNTANT = "accountant", "Accountant"
        PARENT = "parent", "Parent"
        STUDENT = "student", "Student"
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)


class AcademicYear(models.Model):
    name = models.CharField(max_length=20, unique=True)  # e.g. 2026-27
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    def __str__(self): return self.name


class Subject(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    def __str__(self): return self.name


class ClassSection(models.Model):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="sections")
    grade_level = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=10)  # section letter
    class_teacher = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="class_teacher_of")
    class Meta:
        unique_together = ("academic_year", "grade_level", "name")
    def __str__(self): return f"{self.grade_level}-{self.name} ({self.academic_year})"


class TeachingAssignment(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="teaching")
    section = models.ForeignKey(ClassSection, on_delete=models.CASCADE, related_name="assignments")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    class Meta:
        unique_together = ("teacher", "section", "subject")


class Student(models.Model):
    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="student_profile")
    admission_no = models.CharField(max_length=30, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=[("M", "Male"), ("F", "Female"), ("O", "Other")])
    address = models.TextField(blank=True)
    medical_notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes = [models.Index(fields=["last_name", "first_name"])]
    def __str__(self): return f"{self.admission_no} {self.first_name} {self.last_name}"


class Guardian(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="guardian_profile")
    phone = models.CharField(max_length=20, blank=True)
    students = models.ManyToManyField(Student, related_name="guardians")


class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    section = models.ForeignKey(ClassSection, on_delete=models.PROTECT, related_name="enrollments")
    roll_no = models.PositiveIntegerField(null=True, blank=True)
    class Meta:
        unique_together = ("student", "section")


class Assessment(models.Model):
    section = models.ForeignKey(ClassSection, on_delete=models.CASCADE, related_name="assessments")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    term = models.CharField(max_length=20, default="T1")
    max_marks = models.DecimalField(max_digits=6, decimal_places=2)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    date = models.DateField()


class Grade(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="grades")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="grades")
    marks = models.DecimalField(max_digits=6, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = ("assessment", "student")


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "P", "Present"
        ABSENT = "A", "Absent"
        LATE = "L", "Late"
        EXCUSED = "E", "Excused"
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    status = models.CharField(max_length=1, choices=Status.choices)
    marked_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    class Meta:
        unique_together = ("student", "date")
        indexes = [models.Index(fields=["date", "status"])]


class FeeInvoice(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="invoices")
    title = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    due_date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(models.Model):
    invoice = models.ForeignKey(FeeInvoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=30, default="cash")
    reference = models.CharField(max_length=100, blank=True)
    received_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)


class AuditLog(models.Model):
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20)
    model = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
