from rest_framework import viewsets, permissions
from accounts.models import StudentProfile, TeacherProfile, ParentProfile
from academics.models import Grade, Attendance
from core.serializers import StudentProfileSerializer, GradeSerializer, AttendanceSerializer

class StudentProfileViewSet(viewsets.ModelViewSet):
    """
    API endpoint listing et modifiant les profils des élèves.
    Sécurisé par filtrage dynamique en fonction du rôle.
    """
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Les administrateurs et enseignants ont accès à tous les profils
        if user.is_staff or user.role == 'ADMIN':
            return StudentProfile.objects.all()
        elif user.role == 'TEACHER':
            return StudentProfile.objects.all()
        elif user.role == 'STUDENT':
            # Un élève ne voit que son propre profil
            return StudentProfile.objects.filter(user=user)
        elif user.role == 'PARENT':
            # Un parent ne voit que les profils de ses propres enfants
            if hasattr(user, 'parent_profile'):
                return StudentProfile.objects.filter(parent=user.parent_profile)
        return StudentProfile.objects.none()


class GradeViewSet(viewsets.ModelViewSet):
    """
    API endpoint listing et modifiant les notes.
    """
    serializer_class = GradeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.role == 'ADMIN':
            return Grade.objects.all()
        elif user.role == 'TEACHER':
            # Les enseignants voient uniquement les notes qu'ils ont saisies
            if hasattr(user, 'teacher_profile'):
                return Grade.objects.filter(teacher=user.teacher_profile)
            return Grade.objects.none()
        elif user.role == 'STUDENT':
            # Les élèves voient uniquement leurs propres notes
            return Grade.objects.filter(student__user=user)
        elif user.role == 'PARENT':
            # Les parents voient les notes de leurs enfants
            if hasattr(user, 'parent_profile'):
                return Grade.objects.filter(student__parent=user.parent_profile)
        return Grade.objects.none()

    def perform_create(self, serializer):
        # Assigne automatiquement l'enseignant connecté s'il y a lieu
        user = self.request.user
        if user.role == 'TEACHER' and hasattr(user, 'teacher_profile'):
            serializer.save(teacher=user.teacher_profile)
        else:
            serializer.save()


class AttendanceViewSet(viewsets.ModelViewSet):
    """
    API endpoint listing et modifiant les présences/absences.
    """
    serializer_class = AttendanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.role == 'ADMIN':
            return Attendance.objects.all()
        elif user.role == 'TEACHER':
            return Attendance.objects.all()
        elif user.role == 'STUDENT':
            return Attendance.objects.filter(student__user=user)
        elif user.role == 'PARENT':
            if hasattr(user, 'parent_profile'):
                return Attendance.objects.filter(student__parent=user.parent_profile)
        return Attendance.objects.none()
