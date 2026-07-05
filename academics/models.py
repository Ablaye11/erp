from django.db import models

def get_current_school_year():
    from django.apps import apps
    SchoolSettings = apps.get_model('core', 'SchoolSettings')
    return SchoolSettings.get().school_year

class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom de la matière")
    code = models.CharField(max_length=20, unique=True, verbose_name="Code")
    coefficient = models.DecimalField(max_digits=3, decimal_places=1, default=1.0, verbose_name="Coefficient par défaut")
    # Relation M2M : une matière peut être enseignée dans plusieurs classes
    classes = models.ManyToManyField(
        'accounts.SchoolClass',
        blank=True,
        related_name='subjects',
        verbose_name="Classes concernées"
    )

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Matière"
        verbose_name_plural = "Matières"
        ordering = ['name']


class ClassSubjectConfig(models.Model):
    school_class = models.ForeignKey('accounts.SchoolClass', on_delete=models.CASCADE, related_name='subject_configs', verbose_name="Classe")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='class_configs', verbose_name="Matière")
    coefficient = models.DecimalField(max_digits=3, decimal_places=1, default=1.0, verbose_name="Coefficient")

    class Meta:
        verbose_name = "Configuration Matière-Classe"
        verbose_name_plural = "Configurations Matière-Classe"
        unique_together = ('school_class', 'subject')

    def __str__(self):
        return f"{self.school_class.name} - {self.subject.name} (Coef: {self.coefficient})"


class ClassSchedule(models.Model):
    DAY_CHOICES = (
        (1, 'Lundi'),
        (2, 'Mardi'),
        (3, 'Mercredi'),
        (4, 'Jeudi'),
        (5, 'Vendredi'),
    )
    school_class = models.ForeignKey('accounts.SchoolClass', on_delete=models.CASCADE, related_name='schedules', verbose_name="Classe")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="Matière")
    teacher = models.ForeignKey('accounts.TeacherProfile', on_delete=models.CASCADE, verbose_name="Enseignant")
    day_of_week = models.IntegerField(choices=DAY_CHOICES, verbose_name="Jour de la semaine")
    start_time = models.TimeField(verbose_name="Heure de début")
    end_time = models.TimeField(verbose_name="Heure de fin")
    room = models.CharField(max_length=50, blank=True, null=True, verbose_name="Salle")

    def __str__(self):
        return f"{self.school_class.name} - {self.subject.name} ({self.get_day_of_week_display()} {self.start_time}-{self.end_time})"

    class Meta:
        verbose_name = "Emploi du temps"
        verbose_name_plural = "Emplois du temps"

class Grade(models.Model):
    TERM_CHOICES = (
        (1, 'Trimestre 1'),
        (2, 'Trimestre 2'),
        (3, 'Trimestre 3'),
    )
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.CASCADE, related_name='grades', verbose_name="Élève")
    teacher = models.ForeignKey('accounts.TeacherProfile', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enseignant")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="Matière")
    term = models.IntegerField(choices=TERM_CHOICES, verbose_name="Trimestre")
    score = models.DecimalField(max_digits=4, decimal_places=2, verbose_name="Note")
    max_score = models.DecimalField(max_digits=4, decimal_places=2, default=20, verbose_name="Note maximale")
    coefficient = models.DecimalField(max_digits=3, decimal_places=1, default=1.0, verbose_name="Coefficient")
    comment = models.CharField(max_length=255, blank=True, null=True, verbose_name="Commentaire/Appréciation")
    grade_type = models.CharField(
        max_length=15,
        choices=(('DEVOIR', 'Devoir'), ('COMPOSITION', 'Composition')),
        default='COMPOSITION',
        verbose_name="Type d'évaluation"
    )
    devoir_num = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="N° de devoir"
    )
    count_in_bulletin = models.BooleanField(
        default=True,
        verbose_name="Compte dans le bulletin",
        help_text="Si décoché, ce devoir ne sera pas pris en compte dans la moyenne du bulletin."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    school_year = models.CharField(max_length=20, default=get_current_school_year, verbose_name="Année scolaire")

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.subject.name}: {self.score}/{self.max_score}"

    class Meta:
        verbose_name = "Note"
        verbose_name_plural = "Notes"

class Attendance(models.Model):
    STATUS_CHOICES = (
        ('PRESENT', 'Présent'),
        ('ABSENT', 'Absent'),
        ('LATE', 'Retard'),
    )
    PERIOD_CHOICES = (
        ('MATIN', 'Matin (08h-12h)'),
        ('APRES_MIDI', 'Après-midi (14h-17h)'),
    )
    student = models.ForeignKey('accounts.StudentProfile', on_delete=models.CASCADE, related_name='attendances', verbose_name="Élève")
    school_class = models.ForeignKey('accounts.SchoolClass', on_delete=models.CASCADE, related_name='attendances', verbose_name="Classe")
    date = models.DateField(verbose_name="Date")
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='MATIN', verbose_name="Période")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PRESENT', verbose_name="Statut")
    arrival_time = models.TimeField(blank=True, null=True, verbose_name="Heure d'arrivée")
    excuse = models.CharField(max_length=255, blank=True, null=True, verbose_name="Motif / Justification")
    justification_file = models.FileField(upload_to='justifications/', blank=True, null=True, verbose_name="Pièce jointe justificative")
    school_year = models.CharField(max_length=20, default=get_current_school_year, verbose_name="Année scolaire")

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.date} ({self.status})"

    class Meta:
        verbose_name = "Présence / Absence"
        verbose_name_plural = "Présences / Absences"
        unique_together = ('student', 'date', 'period')


class TeacherLeave(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'En attente'),
        ('APPROVED', 'Approuvé'),
        ('REJECTED', 'Refusé'),
    )
    TYPE_CHOICES = (
        ('MALADIE', 'Maladie'),
        ('CONGE', 'Congé annuel'),
        ('FORMATION', 'Formation'),
        ('AUTRE', 'Autre'),
    )
    teacher = models.ForeignKey('accounts.TeacherProfile', on_delete=models.CASCADE, related_name='leaves', verbose_name="Enseignant")
    leave_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='CONGE', verbose_name="Type de congé")
    start_date = models.DateField(verbose_name="Date de début")
    end_date = models.DateField(verbose_name="Date de fin")
    reason = models.CharField(max_length=255, blank=True, verbose_name="Motif")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING', verbose_name="Statut")
    reviewed_by = models.ForeignKey('accounts.AdminProfile', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Examiné par")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.teacher} — {self.get_leave_type_display()} ({self.start_date} → {self.end_date})"

    class Meta:
        verbose_name = "Congé enseignant"
        verbose_name_plural = "Congés enseignants"
        ordering = ['-created_at']


class YearEndReport(models.Model):
    """Bilan de fin d'année scolaire pour un élève — passant, redoublant ou sorti."""
    STATUS_CHOICES = (
        ('PASSANT', 'Passant — Passage en classe supérieure'),
        ('REDOUBLANT', 'Redoublant — Maintien dans la même classe'),
        ('SORTI', 'Sorti — Quitte l\'établissement'),
    )
    student = models.ForeignKey(
        'accounts.StudentProfile',
        on_delete=models.CASCADE,
        related_name='year_end_reports',
        verbose_name="Élève"
    )
    school_year = models.CharField(max_length=20, verbose_name="Année scolaire")
    original_class = models.ForeignKey(
        'accounts.SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        related_name='year_end_originals',
        verbose_name="Classe d'origine"
    )
    final_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name="Moyenne annuelle"
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='PASSANT',
        verbose_name="Décision"
    )
    next_class = models.ForeignKey(
        'accounts.SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='year_end_targets',
        verbose_name="Classe suivante (si passant)"
    )
    validated_by = models.ForeignKey(
        'accounts.AdminProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Validé par"
    )
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation")
    notes = models.TextField(blank=True, verbose_name="Observations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bilan de fin d'année"
        verbose_name_plural = "Bilans de fin d'année"
        unique_together = ('student', 'school_year')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student} — {self.school_year} → {self.get_status_display()}"
