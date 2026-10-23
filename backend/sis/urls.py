from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views as v

r = DefaultRouter()
r.register("students", v.StudentViewSet, basename="student")
r.register("subjects", v.SubjectViewSet, basename="subject")
r.register("sections", v.ClassSectionViewSet, basename="section")
r.register("enrollments", v.EnrollmentViewSet, basename="enrollment")
r.register("assessments", v.AssessmentViewSet, basename="assessment")
r.register("grades", v.GradeViewSet, basename="grade")
r.register("attendance", v.AttendanceViewSet, basename="attendance")
r.register("invoices", v.FeeInvoiceViewSet, basename="invoice")
r.register("payments", v.PaymentViewSet, basename="payment")
r.register("audit-log", v.AuditLogViewSet, basename="auditlog")

urlpatterns = [path("dashboard/", v.dashboard), path("", include(r.urls))]
