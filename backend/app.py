from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from config import *
import os
import json
import pandas as pd
from pymongo import MongoClient
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np  # AJOUT: Import numpy pour le graphique radar
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
                # S'assurer que l'année est un entier
                record['annee'] = int(record['annee'])
            
            # Enregistrer chaque ligne avec upsert pour éviter les doublons
            updated = 0
            inserted = 0
            for record in records:
                result = data_collection.update_one(
                    {"annee": record['annee']}, 
                    {"$set": record}, 
                    upsert=True
                )
                if result.upserted_id:
                    inserted += 1
                else:
                    updated += 1
            
            return jsonify({
                "message": "Fichier traité avec succès", 
                "records_inserted": inserted,
                "records_updated": updated,
                "success": True
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

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
        # Conversion des types
        for key in ['nombre_fie1', 'nombre_fie2', 'nombre_fie3', 'nombre_diplomes']:
            if key in data:
                data[key] = int(data[key])
        
        if 'taux_boursiers' in data:
            data['taux_boursiers'] = float(data['taux_boursiers'])
            
        for key in ['nombre_handicapes', 'nombre_etrangers', 'nombre_demissionnes']:
            if key in data and data[key]:
                data[key] = int(data[key])
            elif key in data and not data[key]:
                data[key] = 0
        
        # Recherche de l'enregistrement à mettre à jour
        query = {"annee": int(data['annee'])}
        
        # Ajout de métadonnées
        data['updated_by'] = current_user['username']
        data['updated_at'] = datetime.utcnow()
        
        # Mise à jour ou insertion si n'existe pas
        result = data_collection.update_one(query, {"$set": data}, upsert=True)
        
        if result.upserted_id:
            message = "Nouvelles données ajoutées avec succès"
        else:
            message = "Données mises à jour avec succès"
            
        return jsonify({"message": message, "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la mise à jour: {str(e)}"}), 500

@app.route('/api/data/delete/<int:annee>', methods=['DELETE'])
@token_required
def delete_data(current_user, annee):
    """Endpoint pour supprimer des données par année"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'delete' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    try:
        # Suppression des données pour l'année spécifiée
        result = data_collection.delete_one({"annee": annee})
        
        if result.deleted_count == 0:
            return jsonify({"error": f"Aucune donnée trouvée pour l'année {annee}"}), 404
            
        return jsonify({"message": f"Données pour l'année {annee} supprimées avec succès", "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500

# AJOUT: Endpoints spécifiques pour les effectifs étudiants
@app.route('/api/effectifs', methods=['GET'])
@token_required
def get_effectifs(current_user):
    """Endpoint pour récupérer toutes les données d'effectifs étudiants"""
    try:
        data = list(data_collection.find({}, {'_id': 0}).sort('annee', -1))
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500

@app.route('/api/effectifs/stats', methods=['GET'])
@token_required
def get_effectifs_stats(current_user):
    """Endpoint pour récupérer les statistiques d'effectifs étudiants"""
    try:
        data = list(data_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(data)
        
        # Calculer les statistiques
        stats = {
            "total_students": {
                "fie1": int(df['nombre_fie1'].sum()),
                "fie2": int(df['nombre_fie2'].sum()),
                "fie3": int(df['nombre_fie3'].sum()),
            },
            "avg_taux_boursiers": float(df['taux_boursiers'].mean() * 100),  # En pourcentage
            "total_diplomes": int(df['nombre_diplomes'].sum()),
            "evolution_annuelle": df.sort_values('annee', ascending=True).to_dict('records'),
            "annees": sorted(df['annee'].unique().tolist())
        }
        
        # Ajouter des statistiques supplémentaires si disponibles
        if 'nombre_handicapes' in df.columns:
            stats["total_handicapes"] = int(df['nombre_handicapes'].sum())
        
        if 'nombre_etrangers' in df.columns:
            stats["total_etrangers"] = int(df['nombre_etrangers'].sum())
        
        if 'nombre_demissionnes' in df.columns:
            stats["total_demissionnes"] = int(df['nombre_demissionnes'].sum())
        
        return jsonify(stats), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors du calcul des statistiques: {str(e)}"}), 500

# Endpoints pour les graphiques spécifiques aux effectifs
@app.route('/api/effectifs/charts/<chart_type>', methods=['GET'])
@token_required
def get_effectifs_chart(current_user, chart_type):
    """Endpoint pour générer des graphiques spécifiques aux effectifs"""
    try:
        data = list(data_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée"}), 404
        
        df = pd.DataFrame(data)
        df = df.sort_values('annee')  # Trier par année
        
        plt.figure(figsize=(12, 8))
        plt.style.use('seaborn-v0_8')
        
        if chart_type == 'evolution':
            # Évolution du nombre d'étudiants par année et par niveau
            df_melted = df.melt(id_vars=['annee'], 
                                value_vars=['nombre_fie1', 'nombre_fie2', 'nombre_fie3'],
                                var_name='niveau', value_name='nombre')
            
            sns.lineplot(data=df_melted, x='annee', y='nombre', hue='niveau', marker='o')
            plt.title('Évolution du nombre d\'étudiants par année et par niveau', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Nombre d\'étudiants', fontsize=12)
            plt.legend(title='Niveau')
            
        elif chart_type == 'repartition_pie':
            # Répartition par niveau (dernière année)
            last_year = df.iloc[-1]
            plt.pie([last_year['nombre_fie1'], last_year['nombre_fie2'], last_year['nombre_fie3']], 
                   labels=['FIE1', 'FIE2', 'FIE3'],
                   autopct='%1.1f%%',
                   colors=['#2f0d73', '#7c50de', '#ac54c7'])
            plt.title(f'Répartition des étudiants par niveau (Année {last_year["annee"]})', fontsize=16)
            
        elif chart_type == 'taux_boursiers':
            # Taux de boursiers par année
            sns.barplot(data=df, x='annee', y='taux_boursiers')
            plt.title('Évolution du taux de boursiers par année', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Taux de boursiers', fontsize=12)
            plt.xticks(rotation=45)
            
        elif chart_type == 'diplomes_bar':
            # Nombre de diplômés par année
            sns.barplot(data=df, x='annee', y='nombre_diplomes')
            plt.title('Évolution du nombre de diplômés par année', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Nombre de diplômés', fontsize=12)
            plt.xticks(rotation=45)
            
        elif chart_type == 'radar_comparison':
            # Radar - Comparaison entre années
            last_years = df.tail(3)
            
            # Création des données pour le radar
            categories = ['FIE1', 'FIE2', 'FIE3', 'Diplômés', 'Boursiers (%)']
            N = len(categories)
            
            # Calcul des angles pour le graphique radar
            angles = [n / float(N) * 2 * np.pi for n in range(N)]
            angles += angles[:1]  # Fermer le cercle
            
            # Création du graphique
            fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
            
            # Ajouter les années au radar
            for i, year_data in enumerate(last_years.iterrows()):
                year = year_data[1]
                values = [year['nombre_fie1'], year['nombre_fie2'], year['nombre_fie3'], 
                         year['nombre_diplomes'], year['taux_boursiers'] * 100]
                values += values[:1]  # Fermer le cercle
                
                ax.plot(angles, values, linewidth=2, linestyle='solid', label=f"Année {year['annee']}")
                ax.fill(angles, values, alpha=0.1)
            
            # Ajouter les catégories
            plt.xticks(angles[:-1], categories)
            
            # Ajouter une légende
            plt.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
            plt.title('Comparaison des indicateurs sur les dernières années', fontsize=16)
            
        elif chart_type == 'categories_speciales':
            # Graphique pour catégories spéciales (handicapés, étrangers, démissions)
            if all(col in df.columns for col in ['nombre_handicapes', 'nombre_etrangers', 'nombre_demissionnes']):
                df_melted = df.melt(id_vars=['annee'], 
                                   value_vars=['nombre_handicapes', 'nombre_etrangers', 'nombre_demissionnes'],
                                   var_name='categorie', value_name='nombre')
                
                # Renommer les catégories pour l'affichage
                categorie_map = {
                    'nombre_handicapes': 'Handicapés',
                    'nombre_etrangers': 'Étrangers',
                    'nombre_demissionnes': 'Démissions'
                }
                df_melted['categorie'] = df_melted['categorie'].map(categorie_map)
                
                sns.barplot(data=df_melted, x='annee', y='nombre', hue='categorie')
                plt.title('Évolution des catégories spéciales d\'étudiants', fontsize=16)
                plt.xlabel('Année', fontsize=12)
                plt.ylabel('Nombre d\'étudiants', fontsize=12)
                plt.xticks(rotation=45)
                plt.legend(title='Catégorie')
            else:
                return jsonify({"error": "Données manquantes pour ce graphique"}), 400
            
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

# Routes standard
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

@app.route('/api/test', methods=['GET'])
def test_api():
    """Endpoint de test pour vérifier que l'API est accessible"""
    return jsonify({"message": "API accessible", "status": "ok"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')