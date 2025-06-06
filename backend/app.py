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
    enseignement_collection = db[MONGO_COLLECTION_ENSEIGNEMENT]
    heures_enseignement_collection = db['heures_enseignement_detaillees']
    rse_collection = db[MONGO_COLLECTION_RSE]


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
    
################################################################### route heures enseignement ######################

@app.route('/api/heures-enseignement/upload', methods=['POST'])
@token_required
def upload_heures_enseignement_file(current_user):
    """Endpoint pour uploader un fichier Excel ou CSV des heures d'enseignement détaillées"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'upload' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
    
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier n'a été sélectionné"}), 400
    
    if file and (file.filename.endswith('.csv') or file.filename.endswith('.xlsx')):
        try:
            # Récupérer des paramètres supplémentaires
            annee_debut = request.form.get('annee_debut', '2020')
            annee_fin = request.form.get('annee_fin', '2021')
            niveau = request.form.get('niveau', 'FIE1')
            semestre = request.form.get('semestre', 'S1')
            
            annee_academique = f"{annee_debut}-{annee_fin}"
            
            # Lecture du fichier
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:  # Excel
                df = pd.read_excel(file)
            
            # Traitement des données et conversion en structure MongoDB
            # Cette partie dépendra de la structure exacte de votre fichier
            # Exemple de structure pour le traitement
            
            # 1. Identifier les lignes d'unités d'enseignement et de matières
            # 2. Extraire les données d'heures
            # 3. Construire la structure hiérarchique
            
            # Exemple simplifié (à adapter selon votre fichier exact)
            unites_enseignement = {}
            current_ue = None
            records_to_insert = []
            
            # Parcourir le DataFrame
            for index, row in df.iterrows():
                # Détecter si c'est une UE (par exemple, si commence par "E1-" pour FIE1)
                ue_prefix = f"E{niveau[-1]}-" if niveau.startswith('FIE') else f"A{niveau[-1]}-"
                
                # Si la valeur dans la colonne 1 (ou autre, à adapter) commence par le préfixe d'UE
                if isinstance(row.get(1), str) and row.get(1).startswith(ue_prefix):
                    current_ue = {
                        "code": row.get(1),
                        "nom": row.get(2, ""),
                        "matieres": []
                    }
                    unites_enseignement[current_ue["code"]] = current_ue
                
                # Si c'est une matière (ligne avec des heures)
                elif current_ue and pd.notna(row.get(5)) and not pd.isna(row.get(3)):
                    # Extraire les heures (CM, TD, TP)
                    try:
                        ects = float(row.get(3, 0)) if pd.notna(row.get(3)) else 0
                        intervenant = row.get(4, "") if pd.notna(row.get(4)) else ""
                        
                        # Heures CM
                        hm_cm = float(row.get(5, 0)) if pd.notna(row.get(5)) else 0
                        hp_cm = float(row.get(6, 0)) if pd.notna(row.get(6)) else 0
                        hr_cm = float(row.get(7, 0)) if pd.notna(row.get(7)) else 0
                        
                        # Heures TD
                        hm_td = float(row.get(9, 0)) if pd.notna(row.get(9)) else 0
                        hp_td = float(row.get(10, 0)) if pd.notna(row.get(10)) else 0
                        hr_td = float(row.get(11, 0)) if pd.notna(row.get(11)) else 0
                        
                        # Heures TP
                        hm_tp = float(row.get(13, 0)) if pd.notna(row.get(13)) else 0
                        hp_tp = float(row.get(14, 0)) if pd.notna(row.get(14)) else 0
                        hr_tp = float(row.get(15, 0)) if pd.notna(row.get(15)) else 0
                        
                        matiere = {
                            "nom": str(row.get(2, "Matière non nommée")),
                            "ects": ects,
                            "intervenant": intervenant,
                            "heures_cm": {
                                "hm": hm_cm,
                                "hp": hp_cm,
                                "hr": hr_cm
                            },
                            "heures_td": {
                                "hm": hm_td,
                                "hp": hp_td,
                                "hr": hr_td
                            },
                            "heures_tp": {
                                "hm": hm_tp,
                                "hp": hp_tp,
                                "hr": hr_tp
                            }
                        }
                        
                        current_ue["matieres"].append(matiere)
                    except Exception as e:
                        print(f"Erreur lors du traitement d'une ligne: {e}")
            
            # Préparer les données pour MongoDB
            for ue_code, ue_data in unites_enseignement.items():
                if ue_data["matieres"]:  # Ne pas insérer les UE sans matières
                    record = {
                        "annee_academique": annee_academique,
                        "annee_debut": int(annee_debut),
                        "annee_fin": int(annee_fin),
                        "niveau": niveau,
                        "semestre": semestre,
                        "unite_enseignement": ue_data,
                        "uploaded_by": current_user['username'],
                        "uploaded_at": datetime.utcnow()
                    }
                    records_to_insert.append(record)
            
            # Supprimer les données existantes pour cette combinaison
            heures_enseignement_collection.delete_many({
                "annee_academique": annee_academique,
                "niveau": niveau,
                "semestre": semestre
            })
            
            # Insérer les nouvelles données
            if records_to_insert:
                result = heures_enseignement_collection.insert_many(records_to_insert)
                
                return jsonify({
                    "message": "Données d'heures d'enseignement importées avec succès",
                    "records_inserted": len(result.inserted_ids),
                    "success": True
                }), 200
            else:
                return jsonify({
                    "warning": "Aucune donnée valide trouvée dans le fichier",
                    "success": False
                }), 400
                
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV et Excel sont acceptés."}), 400


@app.route('/api/heures-enseignement/form', methods=['POST'])
@token_required
def add_heures_enseignement_form(current_user):
    """Endpoint pour ajouter des heures d'enseignement via formulaire"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'edit' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    data = request.json
    
    # Validation des données
    required_fields = ['annee_debut', 'annee_fin', 'niveau', 'semestre', 'unite_enseignement']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"Le champ {field} est requis"}), 400
    
    try:
        # Préparation des données
        annee_academique = f"{data['annee_debut']}-{data['annee_fin']}"
        
        # Préparer le document pour MongoDB
        record = {
            "annee_academique": annee_academique,
            "annee_debut": int(data['annee_debut']),
            "annee_fin": int(data['annee_fin']),
            "niveau": data['niveau'],
            "semestre": data['semestre'],
            "unite_enseignement": data['unite_enseignement'],
            "created_by": current_user['username'],
            "created_at": datetime.utcnow()
        }
        
        # Insérer ou mettre à jour les données
        result = heures_enseignement_collection.update_one(
            {
                "annee_academique": annee_academique,
                "niveau": data['niveau'],
                "semestre": data['semestre'],
                "unite_enseignement.code": data['unite_enseignement']['code']
            },
            {"$set": record},
            upsert=True
        )
        
        if result.upserted_id:
            message = "Nouvelles données d'heures d'enseignement ajoutées avec succès"
        else:
            message = "Données d'heures d'enseignement mises à jour avec succès"
            
        return jsonify({"message": message, "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'ajout des données: {str(e)}"}), 500

@app.route('/api/heures-enseignement', methods=['GET'])
@token_required
def get_heures_enseignement(current_user):
    """Endpoint pour récupérer les données d'heures d'enseignement"""
    try:
        # Paramètres de filtrage
        annee_debut = request.args.get('annee_debut')
        annee_fin = request.args.get('annee_fin')
        niveau = request.args.get('niveau')
        semestre = request.args.get('semestre')
        
        # Construire le filtre en fonction des paramètres fournis
        filter_query = {}
        
        if annee_debut and annee_fin:
            filter_query["annee_academique"] = f"{annee_debut}-{annee_fin}"
        elif annee_debut:
            filter_query["annee_debut"] = int(annee_debut)
        
        if niveau:
            filter_query["niveau"] = niveau
            
        if semestre:
            filter_query["semestre"] = semestre
        
        # Récupérer les données
        data = list(heures_enseignement_collection.find(filter_query, {'_id': 0}))
        
        return jsonify(data), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500

@app.route('/api/heures-enseignement/stats', methods=['GET'])
@token_required
def get_heures_enseignement_stats(current_user):
    """Endpoint pour récupérer les statistiques des heures d'enseignement"""
    try:
        # Paramètres de filtrage
        annee_debut = request.args.get('annee_debut')
        annee_fin = request.args.get('annee_fin')
        niveau = request.args.get('niveau')
        
        # Construire le filtre en fonction des paramètres fournis
        filter_query = {}
        
        if annee_debut and annee_fin:
            filter_query["annee_academique"] = f"{annee_debut}-{annee_fin}"
        elif annee_debut:
            filter_query["annee_debut"] = int(annee_debut)
        
        if niveau:
            filter_query["niveau"] = niveau
        
        # Récupérer les données
        data = list(heures_enseignement_collection.find(filter_query, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée"}), 404
        
        # Calculer les statistiques
        total_ue = 0
        total_matieres = 0
        total_heures = {
            "cm": {"hm": 0, "hp": 0, "hr": 0},
            "td": {"hm": 0, "hp": 0, "hr": 0},
            "tp": {"hm": 0, "hp": 0, "hr": 0}
        }
        
        intervenants = set()
        
        for record in data:
            # Compter les UE
            total_ue += 1
            
            # Parcourir les matières
            for matiere in record["unite_enseignement"]["matieres"]:
                total_matieres += 1
                
                # Ajouter l'intervenant
                if matiere.get("intervenant"):
                    intervenants.add(matiere["intervenant"])
                
                # Ajouter les heures
                for type_heures in ["cm", "td", "tp"]:
                    heures_key = f"heures_{type_heures}"
                    if heures_key in matiere:
                        for mesure in ["hm", "hp", "hr"]:
                            total_heures[type_heures][mesure] += matiere[heures_key].get(mesure, 0)
        
        # Préparer la réponse
        stats = {
            "nombre_ue": total_ue,
            "nombre_matieres": total_matieres,
            "nombre_intervenants": len(intervenants),
            "heures_totales": {
                "cm": {
                    "hm": round(total_heures["cm"]["hm"], 2),
                    "hp": round(total_heures["cm"]["hp"], 2),
                    "hr": round(total_heures["cm"]["hr"], 2)
                },
                "td": {
                    "hm": round(total_heures["td"]["hm"], 2),
                    "hp": round(total_heures["td"]["hp"], 2),
                    "hr": round(total_heures["td"]["hr"], 2)
                },
                "tp": {
                    "hm": round(total_heures["tp"]["hm"], 2),
                    "hp": round(total_heures["tp"]["hp"], 2),
                    "hr": round(total_heures["tp"]["hr"], 2)
                }
            },
            "total_global": {
                "hm": round(
                    total_heures["cm"]["hm"] + 
                    total_heures["td"]["hm"] + 
                    total_heures["tp"]["hm"], 2
                ),
                "hp": round(
                    total_heures["cm"]["hp"] + 
                    total_heures["td"]["hp"] + 
                    total_heures["tp"]["hp"], 2
                ),
                "hr": round(
                    total_heures["cm"]["hr"] + 
                    total_heures["td"]["hr"] + 
                    total_heures["tp"]["hr"], 2
                )
            },
            "filtres_appliques": {
                "annee_academique": f"{annee_debut}-{annee_fin}" if annee_debut and annee_fin else "Toutes",
                "niveau": niveau if niveau else "Tous"
            }
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors du calcul des statistiques: {str(e)}"}), 500

@app.route('/api/heures-enseignement/delete', methods=['DELETE'])
@token_required
def delete_heures_enseignement(current_user):
    """Endpoint pour supprimer des données d'heures d'enseignement"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'delete' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
    
    # Paramètres de suppression
    data = request.json
    
    if not data or not data.get('annee_academique') or not data.get('niveau') or not data.get('semestre'):
        return jsonify({"error": "Paramètres de suppression incomplets"}), 400
    
    try:
        # Critères de suppression
        delete_query = {
            "annee_academique": data['annee_academique'],
            "niveau": data['niveau'],
            "semestre": data['semestre']
        }
        
        # Si un code d'UE est spécifié, supprimer uniquement cette UE
        if data.get('code_ue'):
            delete_query["unite_enseignement.code"] = data['code_ue']
        
        # Supprimer les données
        result = heures_enseignement_collection.delete_many(delete_query)
        
        if result.deleted_count > 0:
            return jsonify({
                "message": f"{result.deleted_count} enregistrements supprimés avec succès",
                "success": True
            }), 200
        else:
            return jsonify({"error": "Aucune donnée trouvée correspondant aux critères"}), 404
            
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500

# Routes pour les listes déroulantes (références)
@app.route('/api/references/annees-academiques', methods=['GET'])
@token_required
def get_annees_academiques(current_user):
    """Récupérer la liste des années académiques disponibles"""
    try:
        # Exécuter une agrégation pour obtenir les années uniques
        pipeline = [
            {"$group": {"_id": "$annee_academique"}},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(heures_enseignement_collection.aggregate(pipeline))
        
        annees = [item["_id"] for item in result]
        
        # Ajouter les années prédéfinies si elles ne sont pas déjà présentes
        annees_predefinies = ["2020-2021", "2024-2025"]
        for annee in annees_predefinies:
            if annee not in annees:
                annees.append(annee)
        
        annees.sort()
        
        return jsonify(annees), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des années: {str(e)}"}), 500

@app.route('/api/references/niveaux', methods=['GET'])
@token_required
def get_niveaux(current_user):
    """Récupérer la liste des niveaux disponibles"""
    try:
        # Exécuter une agrégation pour obtenir les niveaux uniques
        pipeline = [
            {"$group": {"_id": "$niveau"}},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(heures_enseignement_collection.aggregate(pipeline))
        
        niveaux = [item["_id"] for item in result]
        
        # Ajouter les niveaux prédéfinis s'ils ne sont pas déjà présents
        niveaux_predefinis = ["FIE1", "FIE2", "FIE3", "FIE4", "FIE5", "FIA3", "FIA5"]
        for niveau in niveaux_predefinis:
            if niveau not in niveaux:
                niveaux.append(niveau)
        
        niveaux.sort()
        
        return jsonify(niveaux), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des niveaux: {str(e)}"}), 500

###################################### routes RSE #########################
@app.route('/api/rse/stats', methods=['GET'])
@token_required
def get_rse_stats(current_user):
    """Endpoint pour récupérer les statistiques RSE"""
    try:
        data = list(rse_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée RSE trouvée"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(data)
        
        # Calcul des statistiques
        # Répartition par promotion
        promotion_stats = {}
        if 'promotion' in df.columns:
            for promotion in df['promotion'].unique():
                promo_df = df[df['promotion'] == promotion]
                promotion_stats[promotion] = {
                    'total_heures': int(promo_df['heures_cm'].sum() + promo_df['heures_td'].sum() + promo_df['heures_tp'].sum()),
                    'heures_cm': int(promo_df['heures_cm'].sum()),
                    'heures_td': int(promo_df['heures_td'].sum()),
                    'heures_tp': int(promo_df['heures_tp'].sum()),
                    'nombre_activites': len(promo_df)
                }
        
        # Répartition par type d'activité
        type_activite_stats = {}
        if 'type_activite' in df.columns:
            for type_activite in df['type_activite'].unique():
                type_df = df[df['type_activite'] == type_activite]
                type_activite_stats[type_activite] = {
                    'total_heures': int(type_df['heures_cm'].sum() + type_df['heures_td'].sum() + type_df['heures_tp'].sum()),
                    'heures_cm': int(type_df['heures_cm'].sum()),
                    'heures_td': int(type_df['heures_td'].sum()),
                    'heures_tp': int(type_df['heures_tp'].sum()),
                    'nombre_activites': len(type_df)
                }
        
        # Évolution par année
        evolution_stats = {}
        if 'annee' in df.columns:
            for annee in sorted(df['annee'].unique()):
                annee_df = df[df['annee'] == annee]
                evolution_stats[str(annee)] = {
                    'total_heures': int(annee_df['heures_cm'].sum() + annee_df['heures_td'].sum() + annee_df['heures_tp'].sum()),
                    'heures_cm': int(annee_df['heures_cm'].sum()),
                    'heures_td': int(annee_df['heures_td'].sum()),
                    'heures_tp': int(annee_df['heures_tp'].sum()),
                    'nombre_activites': len(annee_df)
                }
        
        # Calcul des totaux globaux
        total_heures_cm = int(df['heures_cm'].sum())
        total_heures_td = int(df['heures_td'].sum())
        total_heures_tp = int(df['heures_tp'].sum())
        total_heures_rse = total_heures_cm + total_heures_td + total_heures_tp
        
        # Calcul des pourcentages pour les graphiques
        format_cours_pourcentage = {
            'CM': round(total_heures_cm / total_heures_rse * 100 if total_heures_rse > 0 else 0, 1),
            'TD': round(total_heures_td / total_heures_rse * 100 if total_heures_rse > 0 else 0, 1),
            'TP': round(total_heures_tp / total_heures_rse * 100 if total_heures_rse > 0 else 0, 1)
        }
        
        # Préparation des données pour les graphiques
        graphiques = {
            'promotions': {
                'labels': list(promotion_stats.keys()),
                'values': [promotion_stats[p]['total_heures'] for p in promotion_stats]
            },
            'evolution': {
                'labels': list(evolution_stats.keys()),
                'values': [evolution_stats[a]['total_heures'] for a in evolution_stats]
            },
            'type_activite': {
                'labels': list(type_activite_stats.keys()),
                'values': [type_activite_stats[t]['total_heures'] for t in type_activite_stats]
            },
            'format_cours': {
                'labels': ['CM', 'TD', 'TP'],
                'values': [total_heures_cm, total_heures_td, total_heures_tp]
            }
        }
        
        # Construire la réponse avec toutes les statistiques
        stats = {
            "total_heures_rse": total_heures_rse,
            "total_activites": len(df),
            "promotions_impliquees": len(df['promotion'].unique()) if 'promotion' in df.columns else 0,
            "etudiants_impliques": 342,  # Valeur simulée - à calculer selon votre logique
            "repartition_par_promotion": promotion_stats,
            "repartition_par_type": type_activite_stats,
            "evolution_annuelle": evolution_stats,
            "donnees_par_element": df.to_dict('records'),
            "annees_disponibles": sorted(df['annee'].unique().tolist()) if 'annee' in df.columns else [],
            "promotions_disponibles": sorted(df['promotion'].unique().tolist()) if 'promotion' in df.columns else [],
            "format_cours_pourcentage": format_cours_pourcentage,
            "graphiques": graphiques
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors du calcul des statistiques RSE: {str(e)}"}), 500

@app.route('/api/rse/data', methods=['GET'])
@token_required
def get_rse_data(current_user):
    """Endpoint pour récupérer toutes les données RSE"""
    try:
        # Paramètres de filtrage
        annee = request.args.get('annee')
        promotion = request.args.get('promotion')
        semestre = request.args.get('semestre')
        type_activite = request.args.get('type_activite')
        
        # Construire le filtre en fonction des paramètres fournis
        filter_query = {}
        
        if annee:
            filter_query["annee"] = int(annee)
            
        if promotion:
            filter_query["promotion"] = promotion
            
        if semestre:
            filter_query["semestre"] = semestre
            
        if type_activite:
            filter_query["type_activite"] = type_activite
        
        # Récupérer les données avec tri par année décroissante
        data = list(rse_collection.find(filter_query, {'_id': 0}).sort('annee', -1))
        
        return jsonify(data), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données RSE: {str(e)}"}), 500

@app.route('/api/rse/add', methods=['POST'])
@token_required
def add_rse_data(current_user):
    """Endpoint pour ajouter/modifier des données RSE"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'edit' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    data = request.json
    
    if not data:
        return jsonify({"error": "Données manquantes"}), 400
    
    # Validation des champs obligatoires
    required_fields = ['annee', 'promotion', 'semestre', 'type_activite', 'heures_cm', 'heures_td', 'heures_tp']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Le champ {field} est requis"}), 400
    
    try:
        # Vérifier le type d'activité
        activites_valides = [
            "Transition écologique et numérique",
            "Responsabilité sociale et environnementale de l'ingénieur",
            "Anthropocène",
            "Numérique responsable",
            "Enjeux socio environnementaux"
        ]
        
        # Le type d'activité est maintenant un champ libre ou sélectionné dans une liste
        # Pas besoin de validation stricte ici
        
        # Conversion des types
        data['annee'] = int(data['annee'])
        data['heures_cm'] = int(data['heures_cm'])
        data['heures_td'] = int(data['heures_td'])
        data['heures_tp'] = int(data['heures_tp'])
        
        # Calcul du total
        data['total_heures'] = data['heures_cm'] + data['heures_td'] + data['heures_tp']
        
        # Ajout de métadonnées
        data['created_by'] = current_user['username']
        data['created_at'] = datetime.utcnow()
        data['updated_by'] = current_user['username']
        data['updated_at'] = datetime.utcnow()
        
        # Vérifier si c'est une mise à jour ou un ajout
        if 'id' in data and data['id']:
            # Mise à jour
            query = {"id": data['id']}
            data['updated_at'] = datetime.utcnow()
            result = rse_collection.update_one(query, {"$set": data}, upsert=True)
            message = "Données RSE mises à jour avec succès"
        else:
            # Nouvel ajout - générer un ID unique
            data['id'] = f"rse_{int(datetime.utcnow().timestamp())}"
            result = rse_collection.insert_one(data)
            message = "Nouvelles données RSE ajoutées avec succès"
            
        return jsonify({"message": message, "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'ajout des données RSE: {str(e)}"}), 500

@app.route('/api/rse/update', methods=['POST'])
@token_required
def update_rse_data(current_user):
    """Endpoint pour mettre à jour des données RSE"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'edit' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    data = request.json
    
    if not data or 'id' not in data:
        return jsonify({"error": "ID manquant pour la mise à jour"}), 400
    
    try:
        # Conversion des types si nécessaire
        if 'heures_cm' in data:
            data['heures_cm'] = int(data['heures_cm'])
        if 'heures_td' in data:
            data['heures_td'] = int(data['heures_td'])
        if 'heures_tp' in data:
            data['heures_tp'] = int(data['heures_tp'])
        
        # Recalculer le total si les heures ont changé
        if any(field in data for field in ['heures_cm', 'heures_td', 'heures_tp']):
            existing_data = rse_collection.find_one({"id": data['id']})
            if existing_data:
                data['total_heures'] = (
                    data.get('heures_cm', existing_data.get('heures_cm', 0)) +
                    data.get('heures_td', existing_data.get('heures_td', 0)) +
                    data.get('heures_tp', existing_data.get('heures_tp', 0))
                )
        
        # Ajout de métadonnées de mise à jour
        data['updated_by'] = current_user['username']
        data['updated_at'] = datetime.utcnow()
        
        # Mise à jour
        result = rse_collection.update_one(
            {"id": data['id']}, 
            {"$set": data}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Aucune donnée trouvée avec cet ID"}), 404
            
        return jsonify({"message": "Données RSE mises à jour avec succès", "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la mise à jour des données RSE: {str(e)}"}), 500

@app.route('/api/rse/delete/<string:rse_id>', methods=['DELETE'])
@token_required
def delete_rse_data(current_user, rse_id):
    """Endpoint pour supprimer des données RSE"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'delete' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
        
    try:
        # Suppression des données
        result = rse_collection.delete_one({"id": rse_id})
        
        if result.deleted_count == 0:
            return jsonify({"error": f"Aucune donnée RSE trouvée avec l'ID {rse_id}"}), 404
            
        return jsonify({"message": "Données RSE supprimées avec succès", "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la suppression des données RSE: {str(e)}"}), 500

@app.route('/api/rse/upload', methods=['POST'])
@token_required
def upload_rse_csv(current_user):
    """Endpoint pour uploader un fichier CSV RSE"""
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
            required_columns = ['annee', 'promotion', 'semestre', 'type_activite', 
                               'heures_cm', 'heures_td', 'heures_tp']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return jsonify({
                    "error": f"Colonnes manquantes: {', '.join(missing_columns)}"
                }), 400
            
            # Conversion du DataFrame en liste de dictionnaires pour MongoDB
            records = df.to_dict('records')
            
            # Ajout de métadonnées et calculs
            for record in records:
                record['id'] = f"rse_{int(datetime.utcnow().timestamp())}_{records.index(record)}"
                record['total_heures'] = int(record['heures_cm']) + int(record['heures_td']) + int(record['heures_tp'])
                record['uploaded_by'] = current_user['username']
                record['uploaded_at'] = datetime.utcnow()
                record['created_by'] = current_user['username']
                record['created_at'] = datetime.utcnow()
                # S'assurer que l'année est un entier
                record['annee'] = int(record['annee'])
                # Assurer que les heures sont des entiers
                record['heures_cm'] = int(record['heures_cm'])
                record['heures_td'] = int(record['heures_td'])
                record['heures_tp'] = int(record['heures_tp'])
            
            # Insertion des nouvelles données
            result = rse_collection.insert_many(records)
            
            return jsonify({
                "message": "Fichier CSV RSE traité avec succès", 
                "records_inserted": len(result.inserted_ids),
                "success": True
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier CSV RSE: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

@app.route('/api/rse/charts/<chart_type>', methods=['GET'])
@token_required
def get_rse_chart(current_user, chart_type):
    """Endpoint pour générer des graphiques spécifiques aux données RSE"""
    try:
        data = list(rse_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée RSE trouvée"}), 404
        
        df = pd.DataFrame(data)
        
        plt.figure(figsize=(12, 8))
        plt.style.use('seaborn-v0_8')
        
        if chart_type == 'promotions_pie':
            # Répartition par promotion
            promotion_totals = df.groupby('promotion')['total_heures'].sum()
            plt.pie(promotion_totals.values, labels=promotion_totals.index, autopct='%1.1f%%')
            plt.title('Répartition des heures RSE par promotion', fontsize=16)
            
        elif chart_type == 'evolution_line':
            # Évolution par année
            evolution = df.groupby('annee')['total_heures'].sum().sort_index()
            plt.plot(evolution.index, evolution.values, marker='o', linewidth=2)
            plt.title('Évolution des heures RSE par année', fontsize=16)
            plt.xlabel('Année')
            plt.ylabel('Heures RSE')
            
        elif chart_type == 'type_activite_bar':
            # Répartition par type d'activité
            type_totals = df.groupby('type_activite')['total_heures'].sum()
            plt.bar(type_totals.index, type_totals.values)
            plt.title('Répartition par type d\'activité RSE', fontsize=16)
            plt.xlabel('Type d\'activité')
            plt.ylabel('Heures')
            plt.xticks(rotation=45, ha='right')
            
        elif chart_type == 'format_cours_doughnut':
            # Répartition CM/TD/TP
            cm_total = df['heures_cm'].sum()
            td_total = df['heures_td'].sum()
            tp_total = df['heures_tp'].sum()
            
            labels = ['CM', 'TD', 'TP']
            sizes = [cm_total, td_total, tp_total]
            
            # Créer un graphique en beignet
            fig, ax = plt.subplots()
            wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%', 
                                              wedgeprops=dict(width=0.5))
            plt.title('Répartition CM/TD/TP en RSE', fontsize=16)
            
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
        return jsonify({"error": f"Erreur lors de la génération du graphique RSE: {str(e)}"}), 500

############################################################ Routes pour les templates (si nécessaire)
@app.route('/')
def home():
    return jsonify({"message": "API AppISIS - Backend opérationnel", "version": "1.0"})

@app.route('/api/test', methods=['GET'])
def test_api():
    """Endpoint de test pour vérifier que l'API est accessible"""
    return jsonify({"message": "API accessible", "status": "ok"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')

