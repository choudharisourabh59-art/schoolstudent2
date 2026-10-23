from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.forms.models import model_to_dict
from .audit import get_current
from .models import (Attendance, AuditLog, Enrollment, FeeInvoice, Grade, Payment, Student)

AUDITED = (Grade, Attendance, FeeInvoice, Payment, Student, Enrollment)

def _log(action, instance):
    user, ip = get_current()
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action, model=instance.__class__.__name__, object_id=str(instance.pk),
        changes=model_to_dict(instance), ip=ip)

@receiver(post_save)
def on_save(sender, instance, created, **kw):
    if sender in AUDITED:
        _log("created" if created else "updated", instance)

@receiver(post_delete)
def on_delete(sender, instance, **kw):
    if sender in AUDITED:
        _log("deleted", instance)
