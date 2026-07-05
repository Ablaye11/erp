import datetime
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from accounts.models import SchoolClass, StudentProfile, TeacherProfile, ParentProfile, AdminProfile
from academics.models import Subject, ClassSchedule, Grade, Attendance
from finances.models import TuitionFee, Payment
from core.models import Message, Notification, DocumentFile

User = get_user_model()

class Command(BaseCommand):
    help = 'Remplir la base de données avec des données de test réalistes pour l\'ERP Scolaire'

    def add_arguments(self, parser):
        parser.add_argument(
            '--preserve-admin',
            type=int,
            default=None,
            help='ID de l\'utilisateur admin à préserver (ne pas supprimer)',
        )

    def handle(self, *args, **kwargs):
        preserve_admin_id = kwargs.get('preserve_admin')
        self.stdout.write('Nettoyage de la base de données...')
        
        # Clear existing data (in dependency order)
        Message.objects.all().delete()
        Notification.objects.all().delete()
        DocumentFile.objects.all().delete()
        Payment.objects.all().delete()
        TuitionFee.objects.all().delete()
        Grade.objects.all().delete()
        Attendance.objects.all().delete()
        ClassSchedule.objects.all().delete()
        Subject.objects.all().delete()
        StudentProfile.objects.all().delete()
        TeacherProfile.objects.all().delete()
        ParentProfile.objects.all().delete()
        SchoolClass.objects.all().delete()

        # Supprimer les profils et users SAUF l'admin courant si précisé
        if preserve_admin_id:
            AdminProfile.objects.exclude(user_id=preserve_admin_id).delete()
            User.objects.exclude(id=preserve_admin_id).delete()
        else:
            AdminProfile.objects.all().delete()
            User.objects.all().delete()
        

        self.stdout.write('Création des classes...')
        c6a = SchoolClass.objects.create(name="6ème A", level="6ème", classroom="Salle 12")
        c6b = SchoolClass.objects.create(name="6ème B", level="6ème", classroom="Salle 13")
        c5a = SchoolClass.objects.create(name="5ème A", level="5ème", classroom="Salle 8")
        c4a = SchoolClass.objects.create(name="4ème A", level="4ème", classroom="Salle 15")
        c3a = SchoolClass.objects.create(name="3ème A", level="3ème", classroom="Salle 10")
        
        self.stdout.write('Création des matières...')
        math = Subject.objects.create(name="Mathématiques", code="MATH")
        fran = Subject.objects.create(name="Français", code="FRAN")
        hist = Subject.objects.create(name="Histoire-Géographie", code="HIST")
        svt = Subject.objects.create(name="Sciences de la Vie et de la Terre", code="SVT")
        phys = Subject.objects.create(name="Physique-Chimie", code="PHYS")
        angl = Subject.objects.create(name="Anglais", code="ANGL")
        
        self.stdout.write('Création des utilisateurs...')
        
        # Admin: Directeur Diop
        diop_user = User.objects.create_user(
            username="diop", email="diop@alnour.sn", first_name="Babacar", last_name="Diop",
            role="ADMIN", is_staff=True, is_superuser=True
        )
        diop_user.set_password("pass123")
        diop_user.save()
        AdminProfile.objects.create(user=diop_user, position="Directeur")
        
        # Personnel Administratif
        sec_user = User.objects.create_user(
            username="faye_mareme", email="faye.m@alnour.sn", first_name="Marème", last_name="Faye",
            role="ADMIN"
        )
        sec_user.set_password("pass123")
        sec_user.save()
        AdminProfile.objects.create(user=sec_user, position="Secrétaire")
        
        compt_user = User.objects.create_user(
            username="seck_ibou", email="seck.i@alnour.sn", first_name="Ibou", last_name="Seck",
            role="ADMIN"
        )
        compt_user.set_password("pass123")
        compt_user.save()
        AdminProfile.objects.create(user=compt_user, position="Comptable")
        
        inf_user = User.objects.create_user(
            username="ba_awa_inf", email="ba.a@alnour.sn", first_name="Awa", last_name="Ba",
            role="ADMIN"
        )
        inf_user.set_password("pass123")
        inf_user.save()
        AdminProfile.objects.create(user=inf_user, position="Infirmière")

        # Teachers
        fall_user = User.objects.create_user(
            username="fall_amadou", email="fall.a@alnour.sn", first_name="Amadou", last_name="Fall",
            role="TEACHER"
        )
        fall_user.set_password("pass123")
        fall_user.save()
        prof_fall = TeacherProfile.objects.create(user=fall_user)
        prof_fall.subjects.add(math)
        
        ndiaye_user = User.objects.create_user(
            username="ndiaye_rokhaya", email="ndiaye.r@alnour.sn", first_name="Rokhaya", last_name="Ndiaye",
            role="TEACHER"
        )
        ndiaye_user.set_password("pass123")
        ndiaye_user.save()
        prof_ndiaye = TeacherProfile.objects.create(user=ndiaye_user)
        prof_ndiaye.subjects.add(fran)
        
        cheikh_user = User.objects.create_user(
            username="diop_cheikh", email="diop.c@alnour.sn", first_name="Cheikh", last_name="Diop",
            role="TEACHER"
        )
        cheikh_user.set_password("pass123")
        cheikh_user.save()
        prof_cheikh = TeacherProfile.objects.create(user=cheikh_user)
        prof_cheikh.subjects.add(phys)
        
        astou_user = User.objects.create_user(
            username="ba_astou", email="ba.as@alnour.sn", first_name="Astou", last_name="Ba",
            role="TEACHER"
        )
        astou_user.set_password("pass123")
        astou_user.save()
        prof_astou = TeacherProfile.objects.create(user=astou_user)
        prof_astou.subjects.add(hist)
        
        oumar_user = User.objects.create_user(
            username="sow_oumar", email="sow.o@alnour.sn", first_name="Oumar", last_name="Sow",
            role="TEACHER"
        )
        oumar_user.set_password("pass123")
        oumar_user.save()
        prof_oumar = TeacherProfile.objects.create(user=oumar_user)
        prof_oumar.subjects.add(svt)

        # Parents
        parent_awa = User.objects.create_user(
            username="sarr_awa", email="awa.sarr@gmail.com", first_name="Awa", last_name="Sarr",
            role="PARENT"
        )
        parent_awa.set_password("pass123")
        parent_awa.save()
        parent_awa_prof = ParentProfile.objects.create(user=parent_awa, phone="77 564 32 10", address="Dakar, Amitié 2")

        # Students
        kofi_user = User.objects.create_user(
            username="sarr_kofi", email="kofi@gmail.com", first_name="Kofi", last_name="Sarr",
            role="STUDENT"
        )
        kofi_user.set_password("pass123")
        kofi_user.save()
        student_kofi = StudentProfile.objects.create(
            user=kofi_user, class_room=c6a, registration_number="2024-001", parent=parent_awa_prof
        )
        
        # Other students
        s2 = User.objects.create_user(username="diallo_mamadou", email="m.diallo@gmail.com", first_name="Mamadou", last_name="Diallo", role="STUDENT")
        s2.set_password("pass123"); s2.save()
        student_mamadou = StudentProfile.objects.create(user=s2, class_room=c3a, registration_number="2024-002")
        
        s3 = User.objects.create_user(username="ba_fatou", email="f.ba@gmail.com", first_name="Fatou", last_name="Ba", role="STUDENT")
        s3.set_password("pass123"); s3.save()
        student_fatou = StudentProfile.objects.create(user=s3, class_room=c6b, registration_number="2024-003")
        
        s4 = User.objects.create_user(username="niang_aissatou", email="a.niang@gmail.com", first_name="Aïssatou", last_name="Niang", role="STUDENT")
        s4.set_password("pass123"); s4.save()
        student_aissatou = StudentProfile.objects.create(user=s4, class_room=c5a, registration_number="2024-004")
        
        s5 = User.objects.create_user(username="fall_ibrahima", email="i.fall@gmail.com", first_name="Ibrahima", last_name="Fall", role="STUDENT")
        s5.set_password("pass123"); s5.save()
        student_ibrahima = StudentProfile.objects.create(user=s5, class_room=c4a, registration_number="2024-005")
        
        s6 = User.objects.create_user(username="sow_mariama", email="m.sow@gmail.com", first_name="Mariama", last_name="Sow", role="STUDENT")
        s6.set_password("pass123"); s6.save()
        student_mariama = StudentProfile.objects.create(user=s6, class_room=c3a, registration_number="2024-006")

        self.stdout.write('Création des emplois du temps...')
        # Lun 08-10 MATH 6A prof_fall
        ClassSchedule.objects.create(school_class=c6a, subject=math, teacher=prof_fall, day_of_week=1, start_time=datetime.time(8,0), end_time=datetime.time(10,0), room="Salle 12")
        # Lun 10-12 SVT 6A prof_oumar
        ClassSchedule.objects.create(school_class=c6a, subject=svt, teacher=prof_oumar, day_of_week=1, start_time=datetime.time(10,0), end_time=datetime.time(12,0), room="Labo")
        # Lun 14-16 FRAN 6A prof_ndiaye
        ClassSchedule.objects.create(school_class=c6a, subject=fran, teacher=prof_ndiaye, day_of_week=1, start_time=datetime.time(14,0), end_time=datetime.time(16,0), room="Salle 12")

        self.stdout.write('Création des notes...')
        # Grades for Kofi Sarr
        Grade.objects.create(student=student_kofi, teacher=prof_fall, subject=math, term=1, score=16.0, comment="Excellent, continue ainsi")
        Grade.objects.create(student=student_kofi, teacher=prof_ndiaye, subject=fran, term=1, score=14.0, comment="Bon niveau général")
        Grade.objects.create(student=student_kofi, teacher=prof_astou, subject=hist, term=1, score=15.0, comment="Très bon travail")
        Grade.objects.create(student=student_kofi, teacher=prof_cheikh, subject=phys, term=1, score=13.0, comment="Assez bien")
        Grade.objects.create(student=student_kofi, teacher=prof_oumar, subject=svt, term=1, score=16.0, comment="Très bien, esprit scientifique")
        
        # Term 2 grades for Kofi Sarr
        Grade.objects.create(student=student_kofi, teacher=prof_fall, subject=math, term=2, score=17.0, comment="Excellent trimestre !")
        Grade.objects.create(student=student_kofi, teacher=prof_ndiaye, subject=fran, term=2, score=14.0, comment="Régulier et appliqué")
        Grade.objects.create(student=student_kofi, teacher=prof_astou, subject=hist, term=2, score=16.0, comment="Participation très active")
        Grade.objects.create(student=student_kofi, teacher=prof_oumar, subject=svt, term=2, score=15.0, comment="Très bien")

        # Grades for sow mariama
        Grade.objects.create(student=student_mariama, teacher=prof_fall, subject=math, term=1, score=17.0, comment="Brillant")

        # Grades for Fall Ibrahima (struggling)
        Grade.objects.create(student=student_ibrahima, teacher=prof_fall, subject=math, term=1, score=9.0, comment="Doit fournir plus d'efforts")

        self.stdout.write('Création des absences et présences...')
        # Absences for Kofi Sarr
        Attendance.objects.create(student=student_kofi, school_class=c6a, date=datetime.date(2024, 12, 2), period='MATIN', status='ABSENT', excuse="Maladie (certificat fourni)")
        Attendance.objects.create(student=student_kofi, school_class=c6a, date=datetime.date(2024, 11, 18), period='MATIN', status='ABSENT', excuse="Visite médicale")
        Attendance.objects.create(student=student_kofi, school_class=c6a, date=datetime.date(2024, 11, 5), period='MATIN', status='LATE', arrival_time=datetime.time(8, 15), excuse="Transport")
        
        # Today attendance
        Attendance.objects.create(student=student_kofi, school_class=c6a, date=datetime.date.today(), period='MATIN', status='PRESENT', arrival_time=datetime.time(7, 58))
        Attendance.objects.create(student=student_fatou, school_class=c6b, date=datetime.date.today(), period='MATIN', status='PRESENT', arrival_time=datetime.time(8, 5))
        Attendance.objects.create(student=student_ibrahima, school_class=c4a, date=datetime.date.today(), period='MATIN', status='PRESENT', arrival_time=datetime.time(7, 55))
        Attendance.objects.create(student=student_mariama, school_class=c3a, date=datetime.date.today(), period='MATIN', status='PRESENT', arrival_time=datetime.time(8, 1))

        self.stdout.write('Création des frais et paiements...')
        t1 = TuitionFee.objects.create(amount=75000.0, term=1, due_date=datetime.date(2024, 9, 30))
        t2 = TuitionFee.objects.create(amount=75000.0, term=2, due_date=datetime.date(2025, 1, 15))
        t3 = TuitionFee.objects.create(amount=75000.0, term=3, due_date=datetime.date(2025, 4, 30))
        
        # Kofi payments
        Payment.objects.create(student=student_kofi, tuition_fee=t1, amount_paid=75000.0, status='PAID', paid_at=timezone.make_aware(datetime.datetime(2024, 9, 15, 10, 30)), payment_method='MOBILE_MONEY')
        Payment.objects.create(student=student_kofi, tuition_fee=t2, amount_paid=75000.0, status='PAID', paid_at=timezone.make_aware(datetime.datetime(2025, 1, 10, 14, 20)), payment_method='BANK_TRANSFER')
        Payment.objects.create(student=student_kofi, tuition_fee=t3, amount_paid=0.0, status='UNPAID')
        
        # Mamadou (late payment)
        Payment.objects.create(student=student_mamadou, tuition_fee=t1, amount_paid=0.0, status='UNPAID')
        # Ibrahima (late payment)
        Payment.objects.create(student=student_ibrahima, tuition_fee=t1, amount_paid=0.0, status='UNPAID')

        self.stdout.write('Création des messages de démonstration...')
        Message.objects.create(sender=diop_user, recipient=parent_awa, content="Réunion parents-professeurs le 15 décembre à 17h00. Merci de confirmer votre présence.")
        Message.objects.create(sender=parent_awa, recipient=diop_user, content="Merci, je serai présent à la réunion.")
        Message.objects.create(sender=diop_user, recipient=parent_awa, content="Parfait. L'ordre du jour vous sera envoyé demain.")

        self.stdout.write('Création des notifications de démonstration...')
        Notification.objects.create(user=diop_user, title="Absence injustifiée — Diallo Mamadou", message="3ème A • Non présent depuis 2 jours. Un parent doit être contacté.", notification_type="ALERT")
        Notification.objects.create(user=diop_user, title="Notes manquantes à saisir", message="Mathématiques 5ème B — délai : demain 18h00", notification_type="ALERT")
        Notification.objects.create(user=diop_user, title="Paiement en retard (45 jours)", message="Famille Diallo — Frais de scolarité T1 — 75 000 FCFA", notification_type="PAYMENT")
        Notification.objects.create(user=diop_user, title="Réunion pédagogique confirmée", message="Demain à 15h00, Salle des professeurs", notification_type="INFO")

        # Notification for parent
        Notification.objects.create(user=parent_awa, title="Absence de Kofi Sarr", message="Kofi a été marqué absent le 2 déc. 2024.", notification_type="ABSENCE")
        Notification.objects.create(user=parent_awa, title="Rapport de notes disponible", message="Le bulletin du Trimestre 1 de Kofi Sarr est en ligne.", notification_type="INFO")

        self.stdout.write(self.style.SUCCESS('Base de données initialisée avec succès !'))
