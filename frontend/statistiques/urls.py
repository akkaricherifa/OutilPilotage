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
    path('update-data/', views.update_data, name='update_data'),
    
    # Administration
    path('admin-users/', views.admin_users, name='admin_users'),
    
    # API Status (AJAX)
    path('api/status/', views.api_status, name='api_status'),




    # Nouvelles routes pour les effectifs étudiants
    path('effectifs-etudiants/', views.effectifs_etudiants, name='effectifs_etudiants'),
    path('effectifs-etudiants/add/', views.update_data, name='effectifs_add_data'),

 # Nouvelles routes pour les enseignants
    path('enseignement/', views.enseignement, name='enseignement'),
    path('enseignement/add-data/', views.enseignement_add_data, name='enseignement_add_data'),
    path('enseignement/upload-csv/', views.enseignement_upload_csv, name='enseignement_upload_csv'),
    path('enseignement/delete/<int:annee>/<str:semestre>/', views.enseignement_delete_data, name='enseignement_delete_data'),
    path('catEnseug/', views.categories_enseignement, name='categories_enseignement'),
    # Ajoutez cette ligne dans la liste urlpatterns
    path('heures-enseignement/', views.heures_enseignement, name='heures_enseignement'),
]
