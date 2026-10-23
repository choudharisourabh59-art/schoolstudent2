from rest_framework import serializers
from .models import (Assessment, Attendance, AuditLog, ClassSection, Enrollment, FeeInvoice,
                     Grade, Payment, Student, Subject)

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ["id", "admission_no", "first_name", "last_name", "date_of_birth", "gender",
                  "address", "medical_notes", "is_active"]
    def to_representation(self, obj):
        data = super().to_representation(obj)
        user = self.context["request"].user
        if user.role == "accountant":
            data.pop("medical_notes", None)
        return data

class SubjectSerializer(serializers.ModelSerializer):
    class Meta: model = Subject; fields = "__all__"

class ClassSectionSerializer(serializers.ModelSerializer):
    class Meta: model = ClassSection; fields = "__all__"

class EnrollmentSerializer(serializers.ModelSerializer):
    class Meta: model = Enrollment; fields = "__all__"

class AssessmentSerializer(serializers.ModelSerializer):
    class Meta: model = Assessment; fields = "__all__"

class GradeSerializer(serializers.ModelSerializer):
    class Meta: model = Grade; fields = "__all__"

class GradeEntrySerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    marks = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0)

class AttendanceSerializer(serializers.ModelSerializer):
    class Meta: model = Attendance; fields = "__all__"

class AttendanceEntrySerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=Student.objects.all())
    status = serializers.ChoiceField(choices=Attendance.Status.choices)

class AttendanceMarkSerializer(serializers.Serializer):
    section = serializers.PrimaryKeyRelatedField(queryset=ClassSection.objects.all())
    date = serializers.DateField()
    records = AttendanceEntrySerializer(many=True)

class FeeInvoiceSerializer(serializers.ModelSerializer):
    paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, default=0)
    balance = serializers.SerializerMethodField()
    class Meta:
        model = FeeInvoice
        fields = ["id", "student", "title", "amount", "due_date", "paid", "balance"]
    def get_balance(self, obj):
        return obj.amount - (getattr(obj, "paid", 0) or 0)

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ["received_by"]
    def validate(self, attrs):
        inv = attrs["invoice"]
        paid = sum(p.amount for p in inv.payments.all())
        if paid + attrs["amount"] > inv.amount:
            raise serializers.ValidationError("Payment exceeds the invoice balance.")
        if attrs["amount"] <= 0:
            raise serializers.ValidationError("Amount must be positive.")
        return attrs

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta: model = AuditLog; fields = "__all__"
