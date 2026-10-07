SECRET_KEY = 'test-secret-key'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sites',
    'rdmo.accounts',
    'rdmo.conditions',
    'rdmo.core',
    'rdmo.domain',
    'rdmo.options',
    'rdmo.projects',
    'rdmo.questions',
    'rdmo.services',
    'rdmo.tasks',
    'rdmo.views',
    'rdmo_radar',
]

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

RADAR_PROVIDER = {
    'authentication_mode': 'credentials',
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
}
