import os
from pathlib import Path
from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me-before-deployment')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [x.strip() for x in os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if x.strip()]
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.staticfiles', 'core', 'farmer']
MIDDLEWARE = ['core.middleware.RequestIDMiddleware', 'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware']
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'core'/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request']}}]
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'
# Database — SQLite default; set DATABASE_URL=postgres://user:pass@host:5432/db for PostgreSQL
import os as _os
_db_url = _os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres'):
    from urllib.parse import urlparse as _up
    _u = _up(_db_url)
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _u.path.lstrip('/'),
        'USER': _u.username or '',
        'PASSWORD': _u.password or '',
        'HOST': _u.hostname or 'localhost',
        'PORT': str(_u.port or 5432),
    }}
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR/'core'/'static']
STATIC_ROOT = BASE_DIR/'staticfiles'
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR/'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
NASA_POWER_TIMEOUT = int(os.getenv('NASA_POWER_TIMEOUT','45'))
NASA_CMR_TIMEOUT = int(os.getenv('NASA_CMR_TIMEOUT','45'))
NASA_EARTHDATA_TOKEN = os.getenv('NASA_EARTHDATA_TOKEN','').strip()
NASA_DOWNLOAD_MAX_MB = int(os.getenv('NASA_DOWNLOAD_MAX_MB','100'))
FAO_TIMEOUT = int(os.getenv('FAO_TIMEOUT','30'))
FAO_API_KEY = os.getenv('FAO_API_KEY','').strip()
# Public demo mode (Render): anonymous visitors get an isolated demo farmer account
PUBLIC_DEMO = os.getenv('PUBLIC_DEMO', '0') == '1'
DATA_ALLOWED_HOSTS = os.getenv('DATA_ALLOWED_HOSTS', '')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', '1') == '1'
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
else:
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
if os.getenv('DJANGO_BEHIND_PROXY', '') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'json': {'()': 'core.logging.JsonFormatter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'json'}},
    'loggers': {
        'core.request': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'agent.tools': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
}
# Production checklist: set DJANGO_DEBUG=0, DJANGO_SECRET_KEY=<random>,
# DJANGO_ALLOWED_HOSTS=<domain>, serve via HTTPS, and set DJANGO_BEHIND_PROXY=1
# when behind a TLS-terminating proxy.
