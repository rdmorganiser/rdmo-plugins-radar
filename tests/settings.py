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
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

USE_TZ = True
ROOT_URLCONF = 'tests.urls'

RADAR_PROVIDER = {
    'radar_url': 'https://radar.example.test',
    'client_id': 'configured-client-id',
    'client_secret': 'client-secret',
    'redirect_uri': 'https://rdmo.example.test/services/oauth/radar/callback/',
}
