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
    path('api/heures-enseignement/data', views.get_heures_enseignement_data, name='heures_enseignement_data'),
    path('heures-enseignement/upload-csv/', views.heures_enseignement_upload_csv, name='heures_enseignement_upload_csv'),
    path('api/heures-enseignement/graph-data/', views.get_heures_enseignement_graph_data, name='heures_enseignement_graph_data'),
    #RSE
    path('rse/', views.rse_view, name='rse'),
    path('rse/add/', views.rse_add_data, name='rse_add_data'),
    path('rse/delete/<str:rse_id>/', views.rse_delete_data, name='rse_delete_data'),
    path('rse/upload-csv/', views.rse_upload_csv, name='rse_upload_csv'),
    path('api/rse-data/', views.get_rse_data, name='get_rse_data'),
    path('api/rse-evolution/', views.get_rse_evolution_data, name='get_rse_evolution_data'),
    path('api/rse-activity-types/', views.get_rse_activity_types, name='get_rse_activity_types'),
    path('api/rse-format-cours/', views.get_rse_format_cours, name='get_rse_format_cours'),
    path('api/rse-hours-by-promotion/', views.get_rse_hours_by_promotion, name='get_rse_hours_by_promotion'),

    #ARION
    path('arion/', views.arion, name='arion'),
    path('api/arion/data', views.arion_api_redirect, name='arion_api_data'),
    path('api/arion/stats', views.arion_api_redirect, name='arion_api_stats'),
    path('api/arion/add', views.arion_api_redirect, name='arion_api_add'),
    path('api/arion/upload', views.arion_api_redirect, name='arion_api_upload'),
    path('api/arion/delete/<str:item_id>/', views.arion_api_delete, name='arion_api_delete'),
    path('api/arion/status-stats/', views.arion_status_stats, name='arion_status_stats'),
    path('api/arion/monthly_stats', views.arion_monthly_stats, name='arion_monthly_stats'),


    # Routes pour les vacataires
    path('vacataire/', views.vacataire, name='vacataire'),
    path('api/vacataire/data/', views.vacataire_data, name='vacataire_data'),
    path('api/vacataire/add-data/', views.vacataire_add_data, name='vacataire_add_data'),
    path('api/vacataire/upload-csv/', views.vacataire_upload_csv, name='vacataire_upload_csv'),
    path('api/vacataire/delete/<str:id>/', views.vacataire_delete, name='vacataire_delete'),
    path('api/vacataire/update/<str:id>/', views.vacataire_update, name='vacataire_update'),
    path('api/vacataire/stats/', views.vacataire_stats, name='vacataire_stats'),


    # Routes pour les categoriees spéciales
    path('cat-special/', views.cat_special, name='cat_special'),

]
    



