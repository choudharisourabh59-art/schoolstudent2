from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import models as m
from . import serializers as s
from .access import ReadAnyWriteRoles, teacher_sections, visible_students
from .audit import set_current


class AuditedMixin:
    """Records who is acting so signal handlers can write the audit log."""
    def initial(self, request, *a, **kw):
        super().initial(request, *a, **kw)
        set_current(request.user, request.META.get("REMOTE_ADDR"))


class StudentViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = s.StudentSerializer
    permission_classes = [ReadAnyWriteRoles]
    write_roles = ("admin",)
    def get_queryset(self):
        qs = visible_students(self.request.user).order_by("last_name", "first_name")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(admission_no__icontains=q))
        return qs

    @action(detail=True, methods=["get"], url_path="report-card")
    def report_card(self, request, pk=None):
        student = self.get_object()
        grades = m.Grade.objects.filter(student=student).select_related("assessment__subject")
        term = request.query_params.get("term")
        if term:
            grades = grades.filter(assessment__term=term)
        acc = defaultdict(lambda: [Decimal(0), Decimal(0)])
        for g in grades:
            a = g.assessment
            acc[a.subject.name][0] += g.marks / a.max_marks * a.weight
            acc[a.subject.name][1] += a.weight
        subjects = []
        for name, (earned, weight) in sorted(acc.items()):
            pct = round(earned / weight * 100, 2) if weight else None
            subjects.append({"subject": name, "percentage": pct, "grade": letter(pct)})
        pcts = [x["percentage"] for x in subjects if x["percentage"] is not None]
        overall = round(sum(pcts) / len(pcts), 2) if pcts else None
        return Response({"student": student.id, "term": term, "subjects": subjects,
                         "overall_percentage": overall, "overall_grade": letter(overall)})


def letter(pct):
    if pct is None:
        return None
    for floor, name in settings.GRADE_SCALE:
        if pct >= floor:
            return name


class SubjectViewSet(AuditedMixin, viewsets.ModelViewSet):
    queryset = m.Subject.objects.all()
    serializer_class = s.SubjectSerializer
    permission_classes = [ReadAnyWriteRoles]


class ClassSectionViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = s.ClassSectionSerializer
    permission_classes = [ReadAnyWriteRoles]
    def get_queryset(self):
        u = self.request.user
        if u.role in ("admin", "principal", "accountant"):
            return m.ClassSection.objects.all()
        if u.role == "teacher":
            return teacher_sections(u)
        return m.ClassSection.objects.filter(enrollments__student__in=visible_students(u)).distinct()


class EnrollmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = s.EnrollmentSerializer
    permission_classes = [ReadAnyWriteRoles]
    def get_queryset(self):
        return m.Enrollment.objects.filter(student__in=visible_students(self.request.user))


class AssessmentViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = s.AssessmentSerializer
    permission_classes = [ReadAnyWriteRoles]
    write_roles = ("admin", "teacher")

    def get_queryset(self):
        u = self.request.user
        if u.role in ("admin", "principal", "accountant"):
            return m.Assessment.objects.all()
        if u.role == "teacher":
            return m.Assessment.objects.filter(section__in=teacher_sections(u))
        return m.Assessment.objects.filter(
            section__enrollments__student__in=visible_students(u)).distinct()

    def _check_teacher(self, user, section, subject):
        if user.role == "admin":
            return
        if not m.TeachingAssignment.objects.filter(teacher=user, section=section, subject=subject).exists():
            raise PermissionDenied("You are not assigned to this class and subject.")

    def perform_create(self, ser):
        self._check_teacher(self.request.user, ser.validated_data["section"], ser.validated_data["subject"])
        ser.save()

    def perform_update(self, ser):
        self._check_teacher(self.request.user, ser.instance.section, ser.instance.subject)
        ser.save()

    @action(detail=True, methods=["post"], url_path="grades")
    def enter_grades(self, request, pk=None):
        a = self.get_object()
        self._check_teacher(request.user, a.section, a.subject)
        ser = s.GradeEntrySerializer(data=request.data, many=True)
        ser.is_valid(raise_exception=True)
        enrolled = set(a.section.enrollments.values_list("student_id", flat=True))
        for row in ser.validated_data:
            if row["student"].id not in enrolled:
                raise ValidationError(f"Student {row['student'].id} is not in this class.")
            if row["marks"] > a.max_marks:
                raise ValidationError(f"Marks for student {row['student'].id} exceed {a.max_marks}.")
        with transaction.atomic():
            for row in ser.validated_data:
                m.Grade.objects.update_or_create(
                    assessment=a, student=row["student"], defaults={"marks": row["marks"]})
        return Response({"saved": len(ser.validated_data)})


class GradeViewSet(AuditedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.GradeSerializer
    def get_queryset(self):
        qs = m.Grade.objects.filter(student__in=visible_students(self.request.user))
        sid = self.request.query_params.get("student")
        return qs.filter(student_id=sid) if sid else qs


class AttendanceViewSet(AuditedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.AttendanceSerializer
    def get_queryset(self):
        qs = m.Attendance.objects.filter(student__in=visible_students(self.request.user))
        p = self.request.query_params
        if p.get("student"): qs = qs.filter(student_id=p["student"])
        if p.get("date"): qs = qs.filter(date=p["date"])
        return qs.order_by("-date")

    @action(detail=False, methods=["post"])
    def mark(self, request):
        ser = s.AttendanceMarkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        section, day = ser.validated_data["section"], ser.validated_data["date"]
        u = request.user
        if u.role == "teacher":
            if section.class_teacher_id != u.id:
                raise PermissionDenied("Only the class teacher can mark attendance.")
        elif u.role != "admin":
            raise PermissionDenied()
        if day > timezone.localdate():
            raise ValidationError("Cannot mark attendance for a future date.")
        enrolled = set(section.enrollments.values_list("student_id", flat=True))
        records = ser.validated_data["records"]
        if any(r["student"].id not in enrolled for r in records):
            raise ValidationError("A listed student is not enrolled in this class.")
        with transaction.atomic():
            for r in records:
                m.Attendance.objects.update_or_create(
                    student=r["student"], date=day,
                    defaults={"status": r["status"], "marked_by": u})
        return Response({"saved": len(records)})


class FeeInvoiceViewSet(AuditedMixin, viewsets.ModelViewSet):
    serializer_class = s.FeeInvoiceSerializer
    permission_classes = [ReadAnyWriteRoles]
    write_roles = ("admin", "accountant")
    def get_queryset(self):
        return (m.FeeInvoice.objects.filter(student__in=visible_students(self.request.user))
                .annotate(paid=Coalesce(Sum("payments__amount"), Decimal(0),
                                        output_field=DecimalField())))


class PaymentViewSet(AuditedMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                     mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Payments are append-only: corrections are made by an admin in the admin site (audited)."""
    serializer_class = s.PaymentSerializer
    permission_classes = [ReadAnyWriteRoles]
    write_roles = ("admin", "accountant")
    def get_queryset(self):
        return m.Payment.objects.filter(invoice__student__in=visible_students(self.request.user))
    def perform_create(self, ser):
        ser.save(received_by=self.request.user)


class IsAuditor(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ("admin", "principal")

class AuditLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = m.AuditLog.objects.order_by("-created_at")
    serializer_class = s.AuditLogSerializer
    permission_classes = [IsAuditor]


@api_view(["GET"])
@permission_classes([IsAuditor])
def dashboard(request):
    today = timezone.localdate()
    since = today - timedelta(days=30)
    att = m.Attendance.objects.filter(date__gte=since).aggregate(
        total=Count("id"), present=Count("id", filter=Q(status__in=["P", "L"])))
    rate = round(att["present"] / att["total"] * 100, 1) if att["total"] else None
    billed = m.FeeInvoice.objects.aggregate(t=Coalesce(Sum("amount"), Decimal(0)))["t"]
    collected = m.Payment.objects.aggregate(t=Coalesce(Sum("amount"), Decimal(0)))["t"]
    return Response({
        "students_active": m.Student.objects.filter(is_active=True).count(),
        "attendance_rate_30d": rate,
        "fees": {"billed": billed, "collected": collected, "outstanding": billed - collected},
        "enrolled_by_grade": list(
            m.Enrollment.objects.filter(section__academic_year__is_current=True)
            .values("section__grade_level").annotate(n=Count("id")).order_by("section__grade_level")),
    })
