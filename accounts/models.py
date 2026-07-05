from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Administration'),
        ('TEACHER', 'Enseignant'),
        ('STUDENT', 'Élève'),
        ('PARENT', 'Parent'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='ADMIN')
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, verbose_name="Photo de profil")

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"

class SchoolClass(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="Nom de la classe")
    level = models.CharField(max_length=50, verbose_name="Niveau")
    classroom = models.CharField(max_length=50, blank=True, null=True, verbose_name="Salle de classe")
    nb_trimestres = models.PositiveSmallIntegerField(default=3, verbose_name="Nombre de trimestres")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Classe"
        verbose_name_plural = "Classes"

class ParentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'PARENT'}, related_name='parent_profile')
    phone = models.CharField(max_length=20, verbose_name="Téléphone")
    address = models.CharField(max_length=255, verbose_name="Adresse")

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = "Profil Parent"
        verbose_name_plural = "Profils Parents"

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'STUDENT'}, related_name='student_profile')
    class_room = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='students', verbose_name="Classe")
    registration_number = models.CharField(max_length=50, unique=True, verbose_name="Matricule")
    parent = models.ForeignKey(ParentProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='children', verbose_name="Parent")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    birth_place = models.CharField(max_length=100, blank=True, default='', verbose_name="Lieu de naissance")

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = "Profil Élève"
        verbose_name_plural = "Profils Élèves"

class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'TEACHER'}, related_name='teacher_profile')
    subjects = models.ManyToManyField('academics.Subject', blank=True, related_name='teachers', verbose_name="Matières enseignées")

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = "Profil Enseignant"
        verbose_name_plural = "Profils Enseignants"

class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'ADMIN'}, related_name='admin_profile')
    position = models.CharField(max_length=100, default="Directeur", verbose_name="Poste")

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    class Meta:
        verbose_name = "Profil Admin"
        verbose_name_plural = "Profils Admin"
