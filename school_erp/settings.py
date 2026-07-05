"""
Django settings for school_erp project.

Les variables sensibles sont lues depuis le fichier .env dans la racine du projet.
Pour la production : copier .env.example → .env et renseigner les valeurs réelles.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Chargeur .env (sans dépendance externe) ─────────────────────────────────
def _load_env(env_file=None):
    """Charge les variables depuis .env dans os.environ s'il existe."""
    env_path = env_file or BASE_DIR / '.env'
    if env_path.exists():
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())

_load_env()

def _env(key, default=None):
    return os.environ.get(key, default)

# ─── Sécurité ────────────────────────────────────────────────────────────────
SECRET_KEY = _env('SECRET_KEY', 'django-insecure-remplacez-en-production')
DEBUG = _env('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = [h.strip() for h in _env('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

# ─── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'axes',
    'rest_framework',
    'rest_framework.authtoken',
    # Local
    'accounts',
    'academics',
    'finances',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',   # BRUTE FORCE PROTECTION
]

ROOT_URLCONF = 'school_erp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'school_erp.wsgi.application'

# ─── Base de données ──────────────────────────────────────────────────────────
# DB_ENGINE=sqlite  → SQLite (développement)
# DB_ENGINE=postgres → PostgreSQL (production)
_db_engine = _env('DB_ENGINE', 'sqlite')

if _db_engine == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _env('DB_NAME', 'school_erp_db'),
            'USER': _env('DB_USER', 'erp_user'),
            'PASSWORD': _env('DB_PASSWORD', ''),
            'HOST': _env('DB_HOST', 'localhost'),
            'PORT': _env('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ─── Authentification ─────────────────────────────────────────────────────────
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# ─── django-axes (Protection brute-force) ─────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
AXES_LOCKOUT_TEMPLATE = None

# ─── Validation des mots de passe ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Dakar'  # Fuseau horaire correct pour le Sénégal
USE_I18N = True
USE_TZ = True

# ─── Fichiers statiques & médias ──────────────────────────────────────────────
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'   # Utilisé par collectstatic en production
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── Auth / Sessions ──────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

SESSION_COOKIE_AGE = 28800          # 8 heures
SESSION_COOKIE_HTTPONLY = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

# ─── Email SMTP ───────────────────────────────────────────────────────────────
# EMAIL_BACKEND=console → emails affichés dans la console (développement)
# EMAIL_BACKEND=smtp    → emails réels envoyés via SMTP (production)
_email_backend = _env('EMAIL_BACKEND', 'console')

if _email_backend == 'smtp':
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = _env('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(_env('EMAIL_PORT', '587'))
    EMAIL_USE_TLS = _env('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = _env('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = _env('EMAIL_HOST_PASSWORD', '')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

DEFAULT_FROM_EMAIL = 'ERP École Al-Nour <noreply@alnour.sn>'

# ─── Sécurité HTTPS (production uniquement) ───────────────────────────────────
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000         # 1 an
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ─── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

if DEBUG:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'].append(
        'rest_framework.renderers.BrowsableAPIRenderer'
    )
