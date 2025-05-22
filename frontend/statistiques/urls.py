# statistiques/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Pages principales
    path('', views.home, name='home'),
    
    # Authentification
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Tableau de bord et fonctionnalités
    path('dashboard/', views.dashboard, name='dashboard'),
    path('upload-csv/', views.upload_csv, name='upload_csv'),
    path('view-data/', views.view_data, name='view_data'),
    path('charts/', views.charts, name='charts'),
    path('update-data/', views.update_data, name='update_data'),
    
    # Administration
    path('admin-users/', views.admin_users, name='admin_users'),
    
    # API Status (AJAX)
    path('api/status/', views.api_status, name='api_status'),
]