from django.contrib import admin
from .models import TuitionFee, Payment, PaymentTransaction

@admin.register(TuitionFee)
class TuitionFeeAdmin(admin.ModelAdmin):
    list_display = ('term', 'school_class', 'amount', 'due_date')
    list_filter = ('term', 'school_class')
    search_fields = ('school_class__name',)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'student', 'tuition_fee', 'amount_paid', 'status', 'paid_at', 'payment_method')
    list_filter = ('status', 'payment_method', 'paid_at')
    search_fields = ('receipt_number', 'student__user__first_name', 'student__user__last_name', 'student__user__username')
    readonly_fields = ('receipt_number',)

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('payment', 'amount', 'paid_at', 'payment_method', 'reference')
    list_filter = ('payment_method', 'paid_at')
    search_fields = ('payment__receipt_number', 'payment__student__user__first_name', 'payment__student__user__last_name', 'reference')

