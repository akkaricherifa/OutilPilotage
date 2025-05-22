from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from config import *
import os
import json
import pandas as pd
from pymongo import MongoClient
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import jwt
from functools import wraps

# Configuration de l'application
app = Flask(__name__)
CORS(app)  # Permet les requêtes cross-origin

# Configuration Flask
app.config['JWT_SECRET_KEY'] = JWT_SECRET_KEY
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=JWT_ACCESS_TOKEN_EXPIRES_HOURS)

# Configuration MongoDB
try:
    client = MongoClient(MONGO_URI)
    print("Connexion MongoDB réussie!")
    
    # Base de données AppISIS
    db = client[MONGO_DB]  
    users_collection = db[MONGO_COLLECTION_USERS]
    data_collection = db[MONGO_COLLECTION_DATA]
    
    print(f"Connexion à la base {MONGO_DB} réussie!")
    print("Collections disponibles:", db.list_collection_names())
    
except Exception as e:
    print("Échec de connexion MongoDB:", e)




# Décorateur pour vérifier l'authentification
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token manquant ou invalide"}), 401
        
        token = auth_header.split(" ")[1]
        
        try:
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expiré"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token invalide"}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated



# Routes d'authentification
@app.route('/api/register', methods=['POST'])
def register():
    """Endpoint pour l'inscription d'un nouvel utilisateur"""
    register_data = request.get_json()
    
    # Validation des données
    if not register_data:
        return jsonify({"error": "Données manquantes"}), 400
    
    required_fields = ['username', 'password', 'email', 'role']
    for field in required_fields:
        if not register_data.get(field):
            return jsonify({"error": f"Le champ {field} est requis"}), 400
    
    username = register_data['username']
    email = register_data['email']
    role = register_data['role']
    
    # Vérification du rôle
    if role not in ROLES.values():
        return jsonify({"error": "Rôle invalide"}), 400
    
    # Vérification si l'utilisateur existe déjà
    if users_collection.find_one({'username': username}):
        return jsonify({"error": "Nom d'utilisateur déjà pris"}), 400
    if users_collection.find_one({'email': email}):
        return jsonify({"error": "Email déjà utilisé"}), 400
    
    # Création du nouvel utilisateur
    new_user = {
        'username': username,
        'password': generate_password_hash(register_data['password']),
        'email': email,
        'role': role,
        'created_at': datetime.utcnow(),
        'is_active': True,
        'last_login': None
    }
    result = users_collection.insert_one(new_user)
    
    return jsonify({
        "message": "Inscription réussie",
        "user_id": str(result.inserted_id),
        "username": username,
        "email": email,
        "role": role
    }), 201




@app.route('/api/login', methods=['POST'])
def login():
    """Endpoint pour l'authentification"""
    auth_data = request.get_json()
    
    if not auth_data or not auth_data.get('username') or not auth_data.get('password'):
        return jsonify({"error": "Identifiants manquants"}), 400
    
    username = auth_data['username']
    password = auth_data['password']
    
    user = users_collection.find_one({"username": username, "is_active": True})
    
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"error": "Identifiants incorrects"}), 401
    
    # Mise à jour de la dernière connexion
    users_collection.update_one(
        {"_id": user['_id']}, 
        {"$set": {"last_login": datetime.utcnow()}}
    )
    
    # Création du token JWT
    expiration = datetime.utcnow() + timedelta(hours=JWT_ACCESS_TOKEN_EXPIRES_HOURS)
    exp_timestamp = int(expiration.timestamp())

    token = jwt.encode({
        'user_id': str(user['_id']),
        'username': username,
        'role': user['role'],
        'exp': exp_timestamp
    }, app.config['JWT_SECRET_KEY'], algorithm="HS256")
    
    return jsonify({
        "message": "Connexion réussie",
        "token": token,
        "user": {
            "id": str(user['_id']),
            "username": username,
            "email": user['email'],
            "role": user['role']
        }
    }), 200

@app.route('/api/check-auth', methods=['GET'])
@token_required
def check_auth(current_user):
    """Vérifie si l'utilisateur est authentifié"""
    return jsonify({
        "authenticated": True,
        "user": current_user
    }), 200

@app.route('/api/logout', methods=['POST'])
@token_required
def logout(current_user):
    """Endpoint pour la déconnexion"""
    return jsonify({"message": "Déconnexion réussie"}), 200

# Routes pour les données
@app.route('/api/upload', methods=['POST'])
@token_required
def upload_file(current_user):
    """Endpoint pour uploader un fichier CSV"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'upload' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
    
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier n'a été sélectionné"}), 400
    
    if file and file.filename.endswith('.csv'):
        try:
            # Lecture du fichier CSV
            df = pd.read_csv(file)
            
            # Validation des colonnes requises
            required_columns = ['annee', 'nombre_fie1', 'nombre_fie2', 'nombre_fie3', 
                              'taux_boursiers', 'nombre_diplomes']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return jsonify({
                    "error": f"Colonnes manquantes: {', '.join(missing_columns)}"
                }), 400
            
            # Conversion du DataFrame en liste de dictionnaires pour MongoDB
            records = df.to_dict('records')
            
            # Ajout de métadonnées
            for record in records:
                record['uploaded_by'] = current_user['username']
                record['uploaded_at'] = datetime.utcnow()
            
            # Suppression des anciennes données (optionnel - à adapter selon vos besoins)
            # data_collection.delete_many({})
            
            # Insertion des nouvelles données
            result = data_collection.insert_many(records)
            
            return jsonify({
                "message": "Fichier traité avec succès", 
                "records_inserted": len(result.inserted_ids),
                "records": records
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

@app.route('/api/statistics', methods=['GET'])
@token_required
def get_statistics(current_user):
    """Endpoint pour récupérer les statistiques"""
    try:
        data = list(data_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(data)
        
        # Calcul des statistiques de base
        stats = {
            "total_students": {
                "fie1": int(df['nombre_fie1'].sum()),
                "fie2": int(df['nombre_fie2'].sum()),
                "fie3": int(df['nombre_fie3'].sum()),
            },
            "avg_taux_boursiers": float(df['taux_boursiers'].mean()),
            "total_diplomes": int(df['nombre_diplomes'].sum()),
            "evolution_annuelle": df[['annee', 'nombre_fie1', 'nombre_fie2', 'nombre_fie3']].to_dict('records'),
            "years_count": len(df['annee'].unique()),
            "latest_year": int(df['annee'].max()) if not df.empty else None
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors du calcul des statistiques: {str(e)}"}), 500

@app.route('/api/data', methods=['GET'])
@token_required
def get_data(current_user):
    """Endpoint pour récupérer toutes les données"""
    try:
        data = list(data_collection.find({}, {'_id': 0}))
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500

@app.route('/api/chart/<chart_type>', methods=['GET'])
@token_required
def get_chart(current_user, chart_type):
    """Endpoint pour générer un graphique"""
    try:
        data = list(data_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée"}), 404
        
        df = pd.DataFrame(data)
        
        plt.figure(figsize=(12, 8))
        plt.style.use('seaborn-v0_8')
        
        if chart_type == 'evolution_etudiants':
            # Évolution du nombre d'étudiants par année et par niveau
            df_melted = df.melt(id_vars=['annee'], 
                                value_vars=['nombre_fie1', 'nombre_fie2', 'nombre_fie3'],
                                var_name='niveau', value_name='nombre')
            
            sns.lineplot(data=df_melted, x='annee', y='nombre', hue='niveau', marker='o')
            plt.title('Évolution du nombre d\'étudiants par année et par niveau', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Nombre d\'étudiants', fontsize=12)
            plt.legend(title='Niveau')
            
        elif chart_type == 'taux_boursiers':
            # Évolution du taux de boursiers
            sns.barplot(data=df, x='annee', y='taux_boursiers')
            plt.title('Évolution du taux de boursiers par année', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Taux de boursiers', fontsize=12)
            plt.xticks(rotation=45)
            
        elif chart_type == 'diplomes':
            # Évolution du nombre de diplômés
            sns.barplot(data=df, x='annee', y='nombre_diplomes')
            plt.title('Évolution du nombre de diplômés par année', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Nombre de diplômés', fontsize=12)
            plt.xticks(rotation=45)
            
        else:
            return jsonify({"error": "Type de graphique non reconnu"}), 400
        
        plt.tight_layout()
        
        # Convertir le graphique en image base64
        img = BytesIO()
        plt.savefig(img, format='png', dpi=150, bbox_inches='tight')
        img.seek(0)
        plt.close()  # Fermer la figure pour libérer la mémoire
        
        # Encoder l'image en base64
        encoded = base64.b64encode(img.getvalue()).decode('utf-8')
        
        return jsonify({"image": encoded}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la génération du graphique: {str(e)}"}), 500

@app.route('/api/update', methods=['POST'])
@token_required
def update_data(current_user):
    """Endpoint pour mettre à jour les données"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'edit' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    data = request.json
    
    if not data or 'annee' not in data:
        return jsonify({"error": "Données invalides - année requise"}), 400
    
    try:
        # Recherche de l'enregistrement à mettre à jour
        query = {"annee": data['annee']}
        
        # Ajout de métadonnées
        data['updated_by'] = current_user['username']
        data['updated_at'] = datetime.utcnow()
        
        # Mise à jour ou insertion si n'existe pas
        result = data_collection.update_one(query, {"$set": data}, upsert=True)
        
        if result.upserted_id:
            message = "Nouvelles données ajoutées avec succès"
        else:
            message = "Données mises à jour avec succès"
            
        return jsonify({"message": message}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la mise à jour: {str(e)}"}), 500

# Routes pour l'administration des utilisateurs
@app.route('/api/users', methods=['GET'])
@token_required
def get_users(current_user):
    """Récupérer la liste des utilisateurs (admin seulement)"""
    if current_user['role'] != 'admin':
        return jsonify({"error": "Accès interdit"}), 403
    
    try:
        users = list(users_collection.find({}, {
            'password': 0,  # Exclure le mot de passe
            '_id': 0
        }))
        return jsonify(users), 200
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des utilisateurs: {str(e)}"}), 500

# Routes pour les templates (si nécessaire)
@app.route('/')
def home():
    return jsonify({"message": "API AppISIS - Backend opérationnel", "version": "1.0"})

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')