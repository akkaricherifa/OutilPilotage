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

    #RSE
    path('rse/', views.rse_view, name='rse'),
    path('rse/add/', views.rse_add_data, name='rse_add_data'),
    path('rse/delete/<str:rse_id>/', views.rse_delete_data, name='rse_delete_data'),


    path('arion/', views.arion, name='arion'),
      # Si vous utilisez la redirection API, ajoutez ces URLs
    path('api/arion/data', views.arion_api_redirect, name='arion_api_data'),
    path('api/arion/stats', views.arion_api_redirect, name='arion_api_stats'),
    path('api/arion/add', views.arion_api_redirect, name='arion_api_add'),
    path('api/arion/upload', views.arion_api_redirect, name='arion_api_upload'),
    path('api/arion/delete/<str:item_id>/', views.arion_api_delete, name='arion_api_delete'),
]
    



