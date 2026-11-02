"""RDMO routes mounted as in an installation, with an application home redirect."""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='projects'), name='home'),
    path('', include('rdmo.core.urls')),
]
