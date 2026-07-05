import os
import sys
import django

# Configuration de Django
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')
django.setup()

# Surcharger ALLOWED_HOSTS pour le serveur de test
from django.conf import settings as django_settings
django_settings.ALLOWED_HOSTS = ['*']

from django.test import Client
from django.contrib.auth import get_user_model
from accounts.models import StudentProfile, TeacherProfile, AdminProfile, ParentProfile, SchoolClass
from academics.models import Subject

User = get_user_model()

def test_profile_edits():
    client = Client()
    
    # 1. Connexion en tant qu'admin
    admin_user = User.objects.filter(role='ADMIN', is_superuser=True).first()
    if not admin_user:
        print("Erreur: Aucun compte admin trouve.")
        return False
        
    print(f"Connexion avec l'admin: {admin_user.username}")
    client.force_login(admin_user)
    
    # --- TEST ETUDIANT ---
    student = StudentProfile.objects.first()
    if student:
        print(f"\n--- Test edition Etudiant (ID: {student.id}) ---")
        # GET formulaire
        url_get = f"/action/edit-student/{student.id}/"
        res_get = client.get(url_get)
        if res_get.status_code == 200:
            print("[OK] GET Formulaire etudiant OK")
        else:
            print(f"[FAIL] GET Formulaire etudiant echoue (Status: {res_get.status_code})")
            return False
            
        # POST modification
        new_class = SchoolClass.objects.exclude(id=student.class_room_id).first()
        post_data = {
            'first_name': 'TestPrenomEleve',
            'last_name': 'TestNomEleve',
            'email': 'elevetest@example.com',
            'class_id': new_class.id if new_class else student.class_room_id,
            'parent_id': student.parent_id if student.parent else ''
        }
        res_post = client.post(url_get, post_data)
        if res_post.status_code in [200, 302]:
            student.refresh_from_db()
            if student.user.first_name == 'TestPrenomEleve' and student.user.email == 'elevetest@example.com':
                print("[OK] POST Modification etudiant validee en base de donnees")
            else:
                print("[FAIL] Les modifications etudiant n'ont pas ete enregistrees correctement")
                return False
        else:
            print(f"[FAIL] POST Modification etudiant echouee (Status: {res_post.status_code})")
            return False
    else:
        print("Aucun etudiant trouve pour le test.")

    # --- TEST ENSEIGNANT ---
    teacher = TeacherProfile.objects.first()
    if teacher:
        print(f"\n--- Test edition Enseignant (ID: {teacher.id}) ---")
        url_get = f"/action/edit-teacher/{teacher.id}/"
        res_get = client.get(url_get)
        if res_get.status_code == 200:
            print("[OK] GET Formulaire enseignant OK")
        else:
            print(f"[FAIL] GET Formulaire enseignant echoue (Status: {res_get.status_code})")
            return False
            
        # POST modification
        post_data = {
            'first_name': 'TestPrenomEnseignant',
            'last_name': 'TestNomEnseignant',
            'email': 'enseignanttest@example.com',
            'subject_id': Subject.objects.first().id if Subject.objects.first() else ''
        }
        res_post = client.post(url_get, post_data)
        if res_post.status_code in [200, 302]:
            teacher.refresh_from_db()
            if teacher.user.first_name == 'TestPrenomEnseignant':
                print("[OK] POST Modification enseignant validee en base de donnees")
            else:
                print("[FAIL] Les modifications enseignant n'ont pas ete enregistrees correctement")
                return False
        else:
            print(f"[FAIL] POST Modification enseignant echouee (Status: {res_post.status_code})")
            return False
    else:
        print("Aucun enseignant trouve pour le test.")

    # --- TEST PERSONNEL ---
    staff = AdminProfile.objects.first()
    if staff:
        print(f"\n--- Test edition Personnel (ID: {staff.id}) ---")
        url_get = f"/action/edit-staff/{staff.id}/"
        res_get = client.get(url_get)
        if res_get.status_code == 200:
            print("[OK] GET Formulaire personnel OK")
        else:
            print(f"[FAIL] GET Formulaire personnel echoue (Status: {res_get.status_code})")
            return False
            
        post_data = {
            'first_name': 'TestPrenomStaff',
            'last_name': 'TestNomStaff',
            'email': 'stafftest@example.com',
            'position': 'Secretaire'
        }
        res_post = client.post(url_get, post_data)
        if res_post.status_code in [200, 302]:
            staff.refresh_from_db()
            if staff.user.first_name == 'TestPrenomStaff' and staff.position == 'Secretaire':
                print("[OK] POST Modification personnel validee en base de donnees")
            else:
                print("[FAIL] Les modifications personnel n'ont pas ete enregistrees correctement")
                return False
        else:
            print(f"[FAIL] POST Modification personnel echouee (Status: {res_post.status_code})")
            return False
    else:
        print("Aucun membre du personnel trouve pour le test.")

    print("\n==============================================")
    print("Tous les tests d'edition de profil ont REUSSI !")
    print("==============================================")
    return True

if __name__ == "__main__":
    test_profile_edits()

