from pathlib import Path
from tempfile import gettempdir

from rdmo.core.settings import *  # noqa: F403

SECRET_KEY = 'test-secret-key'

INSTALLED_APPS = [*INSTALLED_APPS, 'rdmo_radar']  # noqa: F405


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

USE_TZ = True
SITE_ID = 1
MULTISITE = False
PROJECT_TASKS_SYNC = False
PROJECT_VIEWS_SYNC = False
DEFAULT_URI_PREFIX = 'https://example.test/terms'
LANGUAGE_CODE = 'en'
LANGUAGES = [('en', 'English'), ('de', 'Deutsch')]
REPLACE_MISSING_TRANSLATION = True
ROOT_URLCONF = 'tests.urls'
ALLOWED_HOSTS = ['testserver']
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
]

RADAR_PROVIDER = {
    'authentication_mode': 'credentials',
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
}

STATIC_URL = '/static/'
STATIC_ROOT = str(Path(gettempdir()) / 'radar-test-static')
COMPRESS_ENABLED = False
