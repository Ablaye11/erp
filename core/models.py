from django.db import models
from django.conf import settings

class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages', verbose_name="Expéditeur")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_messages', verbose_name="Destinataire")
    content = models.TextField(verbose_name="Message")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"De {self.sender.username} à {self.recipient.username} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        ordering = ['created_at']

class Notification(models.Model):
    TYPE_CHOICES = (
        ('ALERT', 'Urgence / Alerte'),
        ('ABSENCE', 'Absence / Retard'),
        ('PAYMENT', 'Finance / Paiement'),
        ('INFO', 'Information générale'),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name="Utilisateur")
    title = models.CharField(max_length=150, verbose_name="Titre")
    message = models.TextField(verbose_name="Message")
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='INFO', verbose_name="Type de notification")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notif for {self.user.username} - {self.title}"

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']

class DocumentFile(models.Model):
    CATEGORY_CHOICES = (
        ('ELEVES', 'Dossiers élèves'),
        ('BULLETINS', 'Bulletins'),
        ('COURRIERS', 'Courriers'),
        ('CONTRATS', 'Contrats'),
        ('BUDGETS', 'Budgets'),
        ('REGLEMENTS', 'Règlements'),
    )
    name = models.CharField(max_length=150, verbose_name="Nom du document")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='ELEVES', verbose_name="Catégorie")
    file = models.FileField(upload_to='documents/', null=True, blank=True, verbose_name="Fichier")
    file_info = models.CharField(max_length=100, blank=True, null=True, verbose_name="Info / Taille (ex: 487 fichiers, 312 PDF)")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="Uploadeur")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"


class SchoolSettings(models.Model):
    """Singleton — paramètres de configuration de l'établissement."""
    school_name = models.CharField(max_length=150, default="École Al-Nour", verbose_name="Nom")
    school_city = models.CharField(max_length=100, default="Dakar, Sénégal", verbose_name="Ville")
    school_year = models.CharField(max_length=20, default="2024/2025", verbose_name="Année scolaire")
    school_director = models.CharField(max_length=150, default="M. Diop Babacar", verbose_name="Directeur")
    school_email = models.EmailField(default="contact@alnour.sn", verbose_name="Email")
    tuition_fee = models.PositiveIntegerField(default=75000, verbose_name="Frais /trimestre (FCFA)")
    nb_trimestres = models.PositiveSmallIntegerField(default=3, verbose_name="Nb trimestres")
    passing_score = models.DecimalField(max_digits=4, decimal_places=2, default=10.0, verbose_name="Note de passage")
    sms_alerts = models.BooleanField(default=True, verbose_name="Alertes SMS")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paramètres établissement"

    def __str__(self):
        return f"Paramètres — {self.school_name}"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="Utilisateur")
    action = models.CharField(max_length=255, verbose_name="Action")
    model_name = models.CharField(max_length=100, verbose_name="Modèle", blank=True, null=True)
    object_id = models.CharField(max_length=100, verbose_name="ID Objet", blank=True, null=True)
    changes = models.JSONField(verbose_name="Changements (JSON)", blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Horodatage")
    ip_address = models.GenericIPAddressField(verbose_name="Adresse IP", blank=True, null=True)

    class Meta:
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"
        ordering = ['-timestamp']

    def __str__(self):
        user_str = self.user.username if self.user else "Système"
        return f"{user_str} - {self.action} ({self.timestamp.strftime('%d/%m/%Y %H:%M')})"


class SchoolEvent(models.Model):
    TYPE_CHOICES = (
        ('EXAM', 'Examen / Devoir'),
        ('HOLIDAY', 'Congé / Vacances'),
        ('MEETING', 'Réunion / Conseil'),
        ('SPORT', 'Activité sportive'),
        ('CULTURAL', 'Événement culturel'),
        ('OTHER', 'Autre'),
    )
    title = models.CharField(max_length=150, verbose_name="Titre")
    event_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='OTHER', verbose_name="Type")
    start_date = models.DateField(verbose_name="Date de début")
    end_date = models.DateField(blank=True, null=True, verbose_name="Date de fin (optionnel)")
    description = models.CharField(max_length=500, blank=True, verbose_name="Description")
    school_class = models.ForeignKey('accounts.SchoolClass', on_delete=models.SET_NULL, null=True, blank=True, related_name='events', verbose_name="Classe concernée (optionnel)")
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, verbose_name="Créé par")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.start_date})"

    class Meta:
        verbose_name = "Événement scolaire"
        verbose_name_plural = "Événements scolaires"
        ordering = ['start_date']


