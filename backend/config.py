import os

# Configuration de base
DEBUG = True
SECRET_KEY = 'votre-cle-secrete-super-secure-pour-flask-jwt-2024'


# Configuration MongoDB - Base AppISIS
MONGO_URI = 'mongodb://localhost:27017/'
MONGO_DB = 'AppISIS'  # Nouvelle base de données
MONGO_COLLECTION_USERS = 'utilisateurs'  # Collection utilisateurs
MONGO_COLLECTION_DATA = 'donnees_etudiants'  # Collection données
MONGO_COLLECTION_ENSEIGNEMENT = 'donnees_enseignement'
MONGO_COLLECTION_RSE = 'donnees_rse'  # Collection enseignement
# Configuration des uploads
UPLOAD_FOLDER = '../data'
ALLOWED_EXTENSIONS = {'csv'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max

# Rôles utilisateurs
ROLES = {
    'ADMIN': 'admin',
    'RESPONSABLE_RECHERCHE': 'responsable_recherche', 
    'RESPONSABLE_ADMIN': 'responsable_admin',
    'SECRETAIRE': 'secretaire'
}

# CORRECTION: Permissions par rôle - utiliser les valeurs réelles des rôles
PERMISSIONS = {
    'admin': ['upload', 'view', 'edit', 'delete', 'manage_users', 'all_stats'],
    'responsable_recherche': ['view', 'research_stats', 'export'],
    'responsable_admin': ['upload', 'view', 'edit', 'admin_stats'],
    'secretaire': ['view', 'basic_upload']
}


# Configuration JWT
JWT_SECRET_KEY = SECRET_KEY
JWT_ACCESS_TOKEN_EXPIRES_HOURS = 24

