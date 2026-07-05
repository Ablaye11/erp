# 🏫 École Al-Nour ERP

Système de gestion scolaire complet pour établissements primaires et secondaires au Sénégal.
Développé avec **Django 6** + **HTMX** — interface 100% responsive, sans rechargement de page.

---

## 📋 Fonctionnalités

| Module | Description |
|---|---|
| 👥 **Élèves** | Dossiers, matricules automatiques, import CSV |
| 👨‍🏫 **Enseignants** | Profils, matières, congés |
| 📝 **Notes** | Devoirs + Compositions, bulletins trimestriels, classement |
| 📅 **Emplois du temps** | Gestion des créneaux, détection de conflits |
| 🏥 **Absences** | Appel, justificatifs avec pièces jointes |
| 💰 **Finances** | Frais de scolarité, paiements, grand livre, reçus PDF |
| 🎓 **Fin d'année** | Promotion automatique, PV imprimable |
| 🔒 **Sécurité** | Rôles (Admin/Prof/Élève/Parent), protection brute-force |
| 📊 **Admin** | Tableau de bord, audit logs, export Excel |

---

## 🚀 Installation rapide (Développement)

### 1. Cloner et créer l'environnement virtuel

```bash
cd "mes projet sites"
git clone <url_du_repo> erp
cd erp

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer l'environnement

```bash
# Copier le fichier exemple
copy .env.example .env        # Windows
# cp .env.example .env        # Linux / macOS

# Éditer .env avec votre éditeur — les valeurs par défaut fonctionnent en développement
```

### 4. Initialiser la base de données

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. (Optionnel) Charger des données de démonstration

```bash
python manage.py seed_data
```

### 6. Lancer le serveur

```bash
python manage.py runserver
```

→ Ouvrir **http://127.0.0.1:8000**

---

## 🏭 Déploiement en Production

### Étape 1 — Configurer `.env`

Éditer le fichier `.env` avec les valeurs de production :

```env
SECRET_KEY=<votre_cle_secrete_generee>
DEBUG=False
ALLOWED_HOSTS=monecole.sn,www.monecole.sn

DB_ENGINE=postgres
DB_NAME=school_erp_db
DB_USER=erp_user
DB_PASSWORD=<mot_de_passe_fort>
DB_HOST=localhost
DB_PORT=5432

EMAIL_BACKEND=smtp
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@monecole.sn
EMAIL_HOST_PASSWORD=<mot_de_passe_application>
```

**Générer une clé secrète :**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Étape 2 — Installer PostgreSQL et `psycopg2`

```bash
pip install psycopg2-binary
```

Créer la base de données :
```sql
CREATE DATABASE school_erp_db;
CREATE USER erp_user WITH PASSWORD 'mot_de_passe_fort';
GRANT ALL PRIVILEGES ON DATABASE school_erp_db TO erp_user;
```

### Étape 3 — Collecter les fichiers statiques

```bash
python manage.py collectstatic --noinput
python manage.py migrate
```

### Étape 4 — Configurer Gunicorn

```bash
pip install gunicorn
gunicorn school_erp.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

### Étape 5 — Configurer Nginx (exemple)

```nginx
server {
    listen 80;
    server_name monecole.sn www.monecole.sn;

    location /static/ {
        alias /chemin/vers/erp/staticfiles/;
    }

    location /media/ {
        alias /chemin/vers/erp/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🔑 Comptes et Rôles

| Rôle | Description |
|---|---|
| **ADMIN** | Accès complet : élèves, notes, finances, settings |
| **TEACHER** | Saisie des notes, appel, emploi du temps |
| **STUDENT** | Consultation des notes, bulletins, EDT |
| **PARENT** | Suivi de l'enfant, paiements en ligne |

---

## 🗂️ Structure du projet

```
erp/
├── accounts/        # Modèles utilisateurs (User, StudentProfile, TeacherProfile...)
├── academics/       # Notes, absences, emplois du temps, fin d'année
├── finances/        # Frais de scolarité, paiements, transactions
├── core/            # Vues principales, API, audit logs, settings ERP
├── templates/       # Templates HTML (dashboard + partials HTMX)
├── static/          # CSS, JS, manifest PWA
├── media/           # Fichiers uploadés (avatars, justificatifs...)
├── .env             # Variables d'environnement (non commité)
├── .env.example     # Modèle de configuration
└── requirements.txt # Dépendances Python
```

---

## 📦 Stack technique

- **Backend** : Django 6, Django REST Framework
- **Frontend** : HTMX, CSS Variables (mode clair/sombre), Tabler Icons
- **Base de données** : SQLite (dev) / PostgreSQL (prod)
- **Sécurité** : django-axes (brute-force), CSRF, HTTPS headers
- **Export** : openpyxl (Excel), html2pdf.js (PDF)

---

## 📞 Support

Pour toute question ou bug, contacter l'équipe de développement.
