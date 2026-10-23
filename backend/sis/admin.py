from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from . import models as m

@admin.register(m.User)
class SisUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("School", {"fields": ("role",)}),)
    list_display = ("username", "role", "is_active")
    list_filter = ("role", "is_active")

@admin.register(m.Student)
class StudentAdmin(admin.ModelAdmin):
    search_fields = ("admission_no", "first_name", "last_name")
    list_display = ("admission_no", "first_name", "last_name", "is_active")

@admin.register(m.AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model", "object_id")
    def has_add_permission(self, r): return False
    def has_change_permission(self, r, o=None): return False
    def has_delete_permission(self, r, o=None): return False

for model in (m.AcademicYear, m.Subject, m.ClassSection, m.TeachingAssignment, m.Guardian,
              m.Enrollment, m.Assessment, m.Grade, m.Attendance, m.FeeInvoice, m.Payment):
    admin.site.register(model)
