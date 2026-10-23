from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission
from .models import ClassSection, Student

SCHOOL_WIDE = ("admin", "principal", "accountant")

def visible_students(user):
    """Single source of truth for 'which students may this user see'."""
    if user.role in SCHOOL_WIDE:
        return Student.objects.all()
    if user.role == "teacher":
        return Student.objects.filter(enrollments__section__in=teacher_sections(user)).distinct()
    if user.role == "parent":
        return Student.objects.filter(guardians__user=user)
    if user.role == "student":
        return Student.objects.filter(user=user)
    return Student.objects.none()

def teacher_sections(user):
    return ClassSection.objects.filter(
        Q(class_teacher=user) | Q(assignments__teacher=user)).distinct()

class ReadAnyWriteRoles(BasePermission):
    """Any signed-in user may read (queryset scoping limits what); writes need view.write_roles."""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in getattr(view, "write_roles", ("admin",))
