from django.db import models
from django.utils import timezone

def get_current_school_year():
    from django.apps import apps
    SchoolSettings = apps.get_model('core', 'SchoolSettings')
    return SchoolSettings.get().school_year

class TuitionFee(models.Model):
    TERM_CHOICES = (
        (1, 'Trimestre 1'),
        (2, 'Trimestre 2'),
        (3, 'Trimestre 3'),
    )
    school_class = models.ForeignKey('accounts.SchoolClass', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Classe (Optionnel)")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant")
    term = models.IntegerField(choices=TERM_CHOICES, verbose_name="Trimestre")
    due_date = models.DateField(verbose_name="Date limite")
    school_year = models.CharField(max_length=20, default=get_current_school_year, verbose_name="Année scolaire")

    def __str__(self):
        target = self.school_class.name if self.school_class else "Général"
        return f"Frais {self.get_term_display()} - {target} ({int(self.amount)} FCFA)"

    class Meta:
        verbose_name = "Frais de scolarité"
        verbose_name_plural = "Frais de scolarité"

class Payment(models.Model):
    STATUS_CHOICES = (
        ('PAID', 'Payé'),
        ('PARTIAL', 'Partiel'),
        ('UNPAID', 'Impayé'),
    )
    METHOD_CHOICES = (
        ('CASH', 'Espèces'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('BANK_TRANSFER', 'Virement Bancaire'),
        ('CARD', 'Carte Bancaire'),
    )
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.CASCADE, related_name='payments', verbose_name="Élève")
    tuition_fee = models.ForeignKey(TuitionFee, on_delete=models.CASCADE, related_name='payments', verbose_name="Frais de scolarité")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.0, verbose_name="Montant payé")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='UNPAID', verbose_name="Statut")
    paid_at = models.DateTimeField(blank=True, null=True, verbose_name="Payé le")
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='CASH', verbose_name="Mode de paiement")
    receipt_number = models.CharField(max_length=50, blank=True, null=True, unique=True, verbose_name="N° de reçu")

    def __str__(self):
        return f"Paiement {self.student.user.get_full_name()} - {self.tuition_fee.get_term_display()} ({self.status})"

    def save(self, *args, **kwargs):
        # Auto-générer un numéro de reçu comptable unique séquentiel lors du paiement
        if self.status in ['PAID', 'PARTIAL'] and not self.receipt_number:
            if not self.paid_at:
                self.paid_at = timezone.now()
            year = self.paid_at.year
            # Chercher le dernier paiement de l'année avec un reçu
            last_payment = Payment.objects.filter(receipt_number__startswith=f"REC-{year}-").order_by('-receipt_number').first()
            if last_payment and last_payment.receipt_number:
                try:
                    last_seq = int(last_payment.receipt_number.split('-')[-1])
                    seq = last_seq + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.receipt_number = f"REC-{year}-{seq:04d}"
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"


class PaymentTransaction(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions', verbose_name="Paiement")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant versé")
    paid_at = models.DateTimeField(default=timezone.now, verbose_name="Date du versement")
    payment_method = models.CharField(max_length=20, choices=Payment.METHOD_CHOICES, default='CASH', verbose_name="Mode de paiement")
    reference = models.CharField(max_length=100, blank=True, null=True, verbose_name="Référence / Notes")

    def __str__(self):
        return f"Versement {self.payment.receipt_number or self.payment.id} de {int(self.amount)} FCFA"

    class Meta:
        verbose_name = "Transaction de paiement"
        verbose_name_plural = "Transactions de paiement"
        ordering = ['-paid_at']
