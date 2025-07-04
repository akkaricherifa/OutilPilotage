from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from config import *
import os
import json
import io
import uuid
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
import math
from functools import wraps
from bson.objectid import ObjectId

# Configuration de l'application
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["http://localhost:8000", "http://127.0.0.1:8000"]}})

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
    enseignement_collection = db[MONGO_COLLECTION_ENSEIGNEMENT]
    heures_enseignement_collection = db['heures_enseignement_detaillees']
    rse_collection = db[MONGO_COLLECTION_RSE]
    arion_collection = db[MONGO_COLLECTION_ARION]
    vacataire_collection = db[MONGO_COLLECTION_VACATAIRE]
    donnees_vac_collection = db['donnees_vac']
    etudiants_collection = db[MONGO_COLLECTION_ETUDIANT]

# Test simple pour vérifier l'accès aux données
    count = etudiants_collection.count_documents({})
    print(f"Nombre d'étudiants dans la collection: {count}")
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
        'is_active': False,  # Changer à False par défaut
        'is_approved': False,  # Nouveau champ: non approuvé par défaut
        'approval_status': 'pending',  # Nouveau champ: pending, approved, rejected
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
    
    user = users_collection.find_one({"username": username})
    
    if not user:
        print(f"Tentative de connexion: utilisateur {username} non trouvé")
        return jsonify({"error": "Identifiants incorrects"}), 401
        
    if not check_password_hash(user['password'], password):
        print(f"Tentative de connexion: mot de passe incorrect pour {username}")
        return jsonify({"error": "Identifiants incorrects"}), 401
    
    # Log détaillé de l'état du compte
    print(f"Tentative de connexion pour {username}:")
    print(f"  - Role: {user.get('role', 'non défini')}")
    print(f"  - _id: {user.get('_id')}")
    print(f"  - is_approved: {user.get('is_approved', False)}")
    print(f"  - approval_status: {user.get('approval_status', 'non défini')}")
    print(f"  - is_active: {user.get('is_active', False)}")
    
    # Vérifier si le compte est approuvé, sauf pour les administrateurs
    if user.get('role') != 'admin':
        if not user.get('is_approved', False):
            print(f"Connexion refusée: compte {username} non approuvé (is_approved=False)")
            return jsonify({"error": "Votre compte est en attente d'approbation par un administrateur"}), 403
            
        if user.get('approval_status') != 'approved':
            print(f"Connexion refusée: compte {username} non approuvé (approval_status={user.get('approval_status')})")
            return jsonify({"error": "Votre compte est en attente d'approbation par un administrateur"}), 403
    
    # Vérifier si le compte est actif
    if not user.get('is_active', True):
        print(f"Connexion refusée: compte {username} inactif")
        return jsonify({"error": "Votre compte a été désactivé. Veuillez contacter un administrateur"}), 403
    
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
    
    print(f"Connexion réussie pour {username}")
    
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

@app.route('/api/users/approve/<user_id>', methods=['POST'])
@token_required
def approve_user(current_user, user_id):
    """Endpoint pour approuver ou rejeter un utilisateur (admin seulement)"""
    # Vérifier si l'utilisateur est admin
    if current_user['role'] != 'admin':
        return jsonify({"error": "Accès interdit. Seuls les administrateurs peuvent approuver/rejeter des utilisateurs."}), 403
    
    # Récupérer les données de la requête
    data = request.json
    if not data or 'status' not in data:
        return jsonify({"error": "Le paramètre 'status' est requis"}), 400
    
    status = data['status']
    if status not in ['approved', 'rejected']:
        return jsonify({"error": "Statut invalide. Doit être 'approved' ou 'rejected'"}), 400
    
    try:
        # Pour le débogage
        print(f"Approbation de l'utilisateur: ID={user_id}, Status={status}")
        
        # Si le username est fourni dans la requête, l'utiliser directement
        username = data.get('username')
        if username:
            print(f"Recherche de l'utilisateur par username fourni: {username}")
            user = users_collection.find_one({"username": username})
            if user:
                print(f"Utilisateur trouvé par username: {username}")
            else:
                print(f"Aucun utilisateur trouvé avec le username: {username}")
                return jsonify({"error": f"Utilisateur avec le nom {username} introuvable"}), 404
        
        # Si aucun utilisateur n'est trouvé par username, essayer de trouver par l'ID format user-X
        elif user_id and user_id.startswith('user-'):
            try:
                index = int(user_id.split('-')[1]) - 1
                all_users = list(users_collection.find().sort('username', 1))
                
                if 0 <= index < len(all_users):
                    user = all_users[index]
                    print(f"Utilisateur trouvé par index: {user.get('username')}")
                else:
                    return jsonify({"error": f"Index utilisateur invalide: {index}"}), 404
            except Exception as e:
                print(f"Erreur lors de la recherche par index: {str(e)}")
                return jsonify({"error": f"Format d'ID invalide: {user_id}"}), 400
        else:
            # Essayer de trouver par ObjectId ou autre
            try:
                user = users_collection.find_one({"id": user_id})
                if not user:
                    # Essayer ObjectId
                    from bson.objectid import ObjectId
                    if ObjectId.is_valid(user_id):
                        user = users_collection.find_one({"_id": ObjectId(user_id)})
            except Exception as e:
                print(f"Erreur lors de la recherche par ID: {str(e)}")
            
            if not user:
                return jsonify({"error": f"Utilisateur avec ID {user_id} introuvable"}), 404
        
        # Sauvegarder l'_id de l'utilisateur pour la mise à jour
        user_id_for_update = user.get('_id')
        
        # Préparer les données de mise à jour
        update_data = {
            "approval_status": status,
            "is_approved": status == 'approved',
            "is_active": status == 'approved',
            "updated_by": current_user['username'],
            "updated_at": datetime.utcnow()
        }
        
        print(f"Mise à jour pour l'utilisateur {user.get('username')} avec status {status}")
        
        # IMPORTANT: Utilisez correctement l'ID MongoDB pour la mise à jour
        result = users_collection.update_one(
            {"_id": user_id_for_update},  # Utiliser l'_id réel
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            if result.matched_count > 0:
                print(f"Aucune modification effectuée pour {user.get('username')} (déjà {status})")
                return jsonify({
                    "warning": "Aucune modification n'a été effectuée (l'utilisateur a peut-être déjà ce statut)",
                    "status": status
                }), 200
            else:
                print(f"Aucun document trouvé pour la mise à jour avec _id: {user_id_for_update}")
                return jsonify({"error": "Erreur de mise à jour: document non trouvé"}), 500
        
        print(f"Mise à jour réussie: {result.modified_count} document(s) modifié(s)")
        return jsonify({
            "message": f"Utilisateur {status} avec succès",
            "user_id": user_id,
            "status": status,
            "username": user.get('username')
        }), 200
        
    except Exception as e:
        import traceback
        print("Erreur détaillée lors de l'approbation:")
        print(traceback.format_exc())
        return jsonify({"error": f"Erreur lors de l'approbation de l'utilisateur: {str(e)}"}), 500
    
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

############################################################ Routes pour les données etudiants ######################################################################
# Endpoints pour la gestion des étudiants individuels
@app.route('/etudiants/save', methods=['POST'])
@token_required
def save_etudiant(current_user):
    """Endpoint pour enregistrer (ajouter ou modifier) un étudiant"""
    try:
        data = request.json
        
        # Si l'ID est fourni, c'est une modification
        if 'id' in data and data['id']:
            # Vérifier si l'étudiant existe
            etudiant = etudiants_collection.find_one({"id": data['id']})
            
            if not etudiant:
                return jsonify({"error": "Étudiant non trouvé"}), 404
            
            # Mettre à jour les données
            data['updated_by'] = current_user['username']
            data['updated_at'] = datetime.utcnow().isoformat()
            
            result = etudiants_collection.update_one(
                {"id": data['id']},
                {"$set": data}
            )
            
            if result.modified_count == 0:
                return jsonify({"error": "Aucune modification effectuée"}), 400
                
            return jsonify({
                "message": "Étudiant mis à jour avec succès",
                "id": data['id']
            }), 200
        else:
            # C'est un ajout
            # Générer un ID unique
            data['id'] = str(uuid.uuid4())
            
            # Ajouter des métadonnées
            data['created_by'] = current_user['username']
            data['created_at'] = datetime.utcnow().isoformat()
            
            # Insérer dans la base de données
            result = etudiants_collection.insert_one(data)
            
            if not result.inserted_id:
                return jsonify({"error": "Erreur lors de l'ajout de l'étudiant"}), 500
                
            return jsonify({
                "message": "Étudiant ajouté avec succès",
                "id": data['id']
            }), 201
    
    except Exception as e:
        app.logger.error(f"Erreur lors de l'enregistrement de l'étudiant: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({"error": f"Erreur lors de l'enregistrement de l'étudiant: {str(e)}"}), 500
@app.route('/etudiants/delete/<string:etudiant_id>', methods=['DELETE'])
@token_required
def delete_etudiant(current_user, etudiant_id):
    """Endpoint pour supprimer un étudiant"""
    try:
        # Vérifier si l'étudiant existe
        etudiant = etudiants_collection.find_one({"id": etudiant_id})
        
        if not etudiant:
            return jsonify({"error": "Étudiant non trouvé"}), 404
        
        # Supprimer l'étudiant
        result = etudiants_collection.delete_one({"id": etudiant_id})
        
        if result.deleted_count == 0:
            return jsonify({"error": "Aucun étudiant supprimé"}), 400
            
        return jsonify({
            "message": "Étudiant supprimé avec succès",
            "id": etudiant_id
        }), 200
    
    except Exception as e:
        app.logger.error(f"Erreur lors de la suppression de l'étudiant: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({"error": f"Erreur lors de la suppression de l'étudiant: {str(e)}"}), 500

@app.route('/etudiants/liste', methods=['GET'])
@token_required
def get_etudiants_liste(current_user):
    """Endpoint simple pour récupérer les étudiants de la base de données"""
    try:
        # Récupérer tous les étudiants de la collection
        etudiants = list(etudiants_collection.find({}, {'_id': 0}))
        
        # Si aucun étudiant trouvé
        if not etudiants:
            return jsonify({"etudiants": [], "message": "Aucun étudiant trouvé"}), 200
        
        # Calculer les statistiques de base
        total_etudiants = len(etudiants)
        
        # Récupérer les années uniques
        annees = []
        for etudiant in etudiants:
            if 'annee' in etudiant and etudiant['annee'] and etudiant['annee'] not in annees:
                annees.append(etudiant['annee'])
        
        # Comptage par niveau
        niveaux = {}
        for etudiant in etudiants:
            niveau = etudiant.get('niveau', 'Non spécifié')
            niveaux[niveau] = niveaux.get(niveau, 0) + 1
        
        # Comptage par genre
        genres = {}
        for etudiant in etudiants:
            genre = etudiant.get('Genre', 'Non spécifié')
            genres[genre] = genres.get(genre, 0) + 1
        
        # Comptage des boursiers
        boursiers = {"Oui": 0, "Non": 0}
        for etudiant in etudiants:
            boursier = etudiant.get('Boursier(ère)', 'Non')
            if boursier == 'Oui':
                boursiers["Oui"] += 1
            else:
                boursiers["Non"] += 1
        
        # Comptage par nationalité
        nationalites = {}
        for etudiant in etudiants:
            nationalite = etudiant.get('Nationalité', 'Non spécifiée')
            nationalites[nationalite] = nationalites.get(nationalite, 0) + 1
        
        # Calcul du taux de boursiers
        taux_boursiers = (boursiers["Oui"] / total_etudiants * 100) if total_etudiants > 0 else 0
        
        # Créer les statistiques
        stats = {
            "total_etudiants": total_etudiants,
            "niveaux": niveaux,
            "genres": genres,
            "boursiers": boursiers,
            "nationalites": nationalites,
            "annees": sorted(annees),
            "taux_boursiers": taux_boursiers
        }
        
        return jsonify({
            "etudiants": etudiants,
            "stats": stats,
            "message": "Données récupérées avec succès"
        }), 200
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des étudiants: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/etudiants/upload-data', methods=['POST'])
@token_required
def upload_etudiants_data(current_user):
    try:
        data = request.json
        if not data or 'etudiants' not in data:
            return jsonify({"error": "Données invalides"}), 400
        
        # Collection pour les étudiants
        etudiants_collection = db['etudiants']
        
        # Ajouter des métadonnées à chaque étudiant
        for etudiant in data['etudiants']:
            etudiant['created_by'] = current_user['username']
            etudiant['created_at'] = datetime.utcnow().isoformat()
            
            # Ajouter un ID si non fourni
            if 'id' not in etudiant or not etudiant['id']:
                etudiant['id'] = str(uuid.uuid4())
        
        # Insérer les étudiants
        result = etudiants_collection.insert_many(data['etudiants'])
        
        return jsonify({
            "message": "Données d'étudiants importées avec succès",
            "records_inserted": len(result.inserted_ids),
            "success": True
        }), 200
        
    except Exception as e:
        app.logger.error(f"Erreur: {str(e)}")
        return jsonify({"error": str(e)}), 500
# Endpoint pour récupérer la liste des années disponibles

@app.route('/api/etudiants/annees', methods=['GET'])
@token_required
def get_etudiants_annees(current_user):
    """Endpoint pour récupérer la liste des années académiques disponibles"""
    try:
        # Récupération des données de la collection étudiants
        etudiants = list(etudiants_collection.find({}, {'_id': 0, 'annee': 1}))
        
        if not etudiants:
            return jsonify({"annees": []}), 200
        
        # Convertir en DataFrame pandas
        df = pd.DataFrame(etudiants)
        
        # Vérifier si la colonne 'annee' existe
        if 'annee' not in df.columns:
            return jsonify({"annees": []}), 200
        
        # Récupérer les années uniques
        annees = sorted(df['annee'].unique().tolist())
        
        return jsonify({"annees": annees}), 200
    
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des années: {str(e)}")
        return jsonify({"error": f"Erreur lors de la récupération des années: {str(e)}"}), 500


@app.route('/api/etudiants', methods=['GET'])
def get_etudiants():  # J'ai supprimé le décorateur @token_required temporairement pour simplifier
    """Endpoint pour récupérer tous les étudiants"""
    try:
        # Vérifier si une limite est spécifiée dans la requête
        limit = request.args.get('limit', None)
        
        # Créer la requête de base
        query = {}
        
        # Compter le nombre total de documents pour info
        total_count = etudiants_collection.count_documents(query)
        print(f"Nombre total d'étudiants dans la collection: {total_count}")
        
        # Récupérer tous les étudiants (sans limite par défaut)
        if limit:
            limit = int(limit)
            cursor = etudiants_collection.find(query, {'_id': 0}).limit(limit)
        else:
            cursor = etudiants_collection.find(query, {'_id': 0})
        
        etudiants = list(cursor)
        
        # Convertir les _id ObjectId en chaînes si nécessaire
        for etudiant in etudiants:
            if '_id' in etudiant:
                etudiant['_id'] = str(etudiant['_id'])
        
        print(f"Nombre d'étudiants récupérés: {len(etudiants)}")
        if etudiants:
            print(f"Premier étudiant: {etudiants[0]}")
        
        return jsonify(etudiants), 200
    
    except Exception as e:
        print(f"ERREUR lors de la récupération des étudiants: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": f"Erreur lors de la récupération des étudiants: {str(e)}"}), 500
@app.route('/api/etudiants/niveaux', methods=['GET'])
def get_etudiants_niveaux():
    """Endpoint pour récupérer tous les niveaux d'étudiants disponibles"""
    try:
        # Utiliser distinct pour récupérer tous les niveaux uniques
        niveaux = etudiants_collection.distinct("niveau")
        
        # Filtrer les valeurs None ou vides
        niveaux = [niveau for niveau in niveaux if niveau]
        
        # Trier les niveaux
        niveaux.sort()
        
        print(f"Niveaux disponibles: {niveaux}")
        
        return jsonify({"niveaux": niveaux}), 200
    
    except Exception as e:
        print(f"ERREUR lors de la récupération des niveaux: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": f"Erreur lors de la récupération des niveaux: {str(e)}"}), 500
@app.route('/api/etudiants/add', methods=['POST'])
@token_required
def add_etudiant(current_user):
    """Endpoint pour ajouter un étudiant"""
    try:
        data = request.form.to_dict()
        
        # Vérification des champs obligatoires
        required_fields = ['Nom', 'Prénom', 'Genre', 'niveau', 'annee']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"success": False, "message": f"Le champ '{field}' est obligatoire"}), 400
        
        # Ajout des métadonnées
        data['created_by'] = current_user['username']
        data['created_at'] = datetime.utcnow().isoformat()
        
        # Ajout d'un ID si non fourni
        if 'id' not in data or not data['id']:
            data['id'] = str(uuid.uuid4())
        
        # Insertion dans la base de données
        result = etudiants_collection.insert_one(data)
        
        if result.inserted_id:
            return jsonify({
                "success": True,
                "message": "Étudiant ajouté avec succès",
                "id": data['id']
            }), 201
        else:
            return jsonify({"success": False, "message": "Erreur lors de l'ajout de l'étudiant"}), 500
    
    except Exception as e:
        app.logger.error(f"Erreur lors de l'ajout d'un étudiant: {str(e)}")
        return jsonify({"success": False, "message": f"Erreur lors de l'ajout de l'étudiant: {str(e)}"}), 500
   
@app.route('/api/etudiants/stats', methods=['GET'])
@token_required
def get_etudiants_stats(current_user):
    """Endpoint pour récupérer les statistiques des étudiants individuels"""
    try:
        # Récupération des données de la collection étudiants
        etudiants = list(etudiants_collection.find({}, {'_id': 0}))
        
        if not etudiants:
            return jsonify({"error": "Aucun étudiant trouvé dans la base de données"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(etudiants)
        
        # 1. Taux de boursiers
        # Vérification de l'existence de la colonne "Boursier(ère)"
        boursiers_data = {}
        if 'Boursier(ère)' in df.columns:
            # Remplacer les valeurs vides par 'Non'
            df['Boursier(ère)'] = df['Boursier(ère)'].fillna('Non')
            
            # Compter les boursiers et non-boursiers
            boursiers_count = (df['Boursier(ère)'].str.lower() == 'oui').sum()
            non_boursiers_count = (df['Boursier(ère)'].str.lower() == 'non').sum()
            total = boursiers_count + non_boursiers_count
            
            # Calculer les pourcentages
            taux_boursiers = (boursiers_count / total * 100) if total > 0 else 0
            taux_non_boursiers = (non_boursiers_count / total * 100) if total > 0 else 0
            
            boursiers_data = {
                'boursiers': int(boursiers_count),
                'non_boursiers': int(non_boursiers_count),
                'taux_boursiers': float(taux_boursiers),
                'taux_non_boursiers': float(taux_non_boursiers)
            }
        
        # 2. Répartition par niveau d'étude
        niveaux_data = {}
        if 'niveau' in df.columns:
            # Compter les étudiants par niveau
            niveau_counts = df['niveau'].value_counts().to_dict()
            niveaux_data = {
                'counts': niveau_counts,
                'total': len(df)
            }
        
        # 3. Répartition par genre
        genre_data = {}
        if 'Genre' in df.columns:
            # Remplacer les valeurs nulles par une chaîne vide
            df['Genre'] = df['Genre'].fillna('')
            
            # Compter les genres
            masculin_count = (df['Genre'].str.lower() == 'masculin').sum()
            feminin_count = (df['Genre'].str.lower() == 'féminin').sum()
            total = masculin_count + feminin_count
            
            # Calculer les pourcentages
            taux_masculin = (masculin_count / total * 100) if total > 0 else 0
            taux_feminin = (feminin_count / total * 100) if total > 0 else 0
            
            genre_data = {
                'masculin': int(masculin_count),
                'feminin': int(feminin_count),
                'taux_masculin': float(taux_masculin),
                'taux_feminin': float(taux_feminin)
            }
        
        # 4. Taux d'étudiants étrangers par niveau
        etrangers_data = {}
        if 'Etranger(ère)' in df.columns and 'niveau' in df.columns:
            # Remplacer les valeurs vides
            df['Etranger(ère)'] = df['Etranger(ère)'].fillna('')
            
            # Pour les valeurs vides, vérifier la nationalité
            mask_vide = df['Etranger(ère)'] == ''
            if 'Nationalité' in df.columns:
                df.loc[mask_vide, 'Etranger(ère)'] = df.loc[mask_vide, 'Nationalité'].apply(
                    lambda x: 'Non' if x == 'Française' else 'Oui' if x else 'Non'
                )
            else:
                df.loc[mask_vide, 'Etranger(ère)'] = 'Non'
            
            # Grouper par niveau et calculer le taux d'étrangers
            etrangers_par_niveau = df.groupby('niveau').apply(
                lambda x: {
                    'total': len(x),
                    'etrangers': (x['Etranger(ère)'].str.lower() == 'oui').sum(),
                    'taux_etrangers': ((x['Etranger(ère)'].str.lower() == 'oui').sum() / len(x) * 100) if len(x) > 0 else 0
                }
            ).to_dict()
            
            etrangers_data = {
                'par_niveau': etrangers_par_niveau,
                'total_etrangers': (df['Etranger(ère)'].str.lower() == 'oui').sum(),
                'taux_global': ((df['Etranger(ère)'].str.lower() == 'oui').sum() / len(df) * 100) if len(df) > 0 else 0
            }
        
        # 5. Évolution du nombre d'étudiants par niveau et par année
        evolution_data = {}
        if 'niveau' in df.columns and 'annee' in df.columns:
            # Remplacer les valeurs manquantes
            if df['annee'].dtype == 'object':
                # Si annee est une chaîne de caractères, extraire l'année de début (ex: "2021-2022" -> "2021")
                df['annee_start'] = df['annee'].str.split('-').str[0]
            else:
                df['annee_start'] = df['annee']
            
            # Grouper par année et niveau
            evolution = df.groupby(['annee_start', 'niveau']).size().unstack(fill_value=0).to_dict()
            evolution_data = {
                'par_annee_niveau': evolution,
                'annees': sorted(df['annee_start'].unique().tolist())
            }
        
        # Assembler toutes les statistiques
        stats = {
            'boursiers': boursiers_data,
            'niveaux': niveaux_data,
            'genre': genre_data,
            'etrangers': etrangers_data,
            'evolution': evolution_data,
            'annees': sorted(df['annee'].unique().tolist()) if 'annee' in df.columns else []
        }
        
        return jsonify(stats), 200
    
    except Exception as e:
        app.logger.error(f"Erreur lors du calcul des statistiques étudiants: {str(e)}")
        return jsonify({"error": f"Erreur lors du calcul des statistiques: {str(e)}"}), 500

@app.route('/api/etudiants/chart/<chart_type>', methods=['GET'])
@token_required
def get_etudiants_chart(current_user, chart_type):
    """Endpoint pour générer des graphiques spécifiques aux étudiants"""
    try:
        # Récupération des données de la collection étudiants
        etudiants = list(etudiants_collection.find({}, {'_id': 0}))
        
        if not etudiants:
            return jsonify({"error": "Aucun étudiant trouvé dans la base de données"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(etudiants)
        
        # Paramètres du graphique
        plt.figure(figsize=(12, 8))
        plt.style.use('seaborn-v0_8')
        
        if chart_type == 'boursiers_pie':
            # Vérification de l'existence de la colonne "Boursier(ère)"
            if 'Boursier(ère)' not in df.columns:
                return jsonify({"error": "Données de boursiers non disponibles"}), 400
                
            # Remplacer les valeurs vides par 'Non'
            df['Boursier(ère)'] = df['Boursier(ère)'].fillna('Non')
            
            # Compter les boursiers et non-boursiers
            boursiers_count = (df['Boursier(ère)'].str.lower() == 'oui').sum()
            non_boursiers_count = (df['Boursier(ère)'].str.lower() == 'non').sum()
            
            # Créer le camembert
            plt.pie([boursiers_count, non_boursiers_count], 
                   labels=['Boursiers', 'Non-boursiers'],
                   autopct='%1.1f%%',
                   colors=['#3366cc', '#dc3912'],
                   startangle=90)
            plt.title('Répartition des étudiants boursiers', fontsize=16)
            
        elif chart_type == 'niveaux_bar':
            # Vérification de l'existence de la colonne "niveau"
            if 'niveau' not in df.columns:
                return jsonify({"error": "Données de niveau non disponibles"}), 400
            
            # Paramètre pour filtrer par année
            annee_filter = request.args.get('annee')
            
            # Filtrer par année si spécifiée
            if annee_filter and 'annee' in df.columns:
                df = df[df['annee'] == annee_filter]
            
            # Compter les étudiants par niveau
            niveau_counts = df['niveau'].value_counts().sort_index()
            
            # Créer le graphique en barres
            bars = plt.bar(niveau_counts.index, niveau_counts.values, color='#3366cc')
            
            # Ajouter les valeurs sur les barres
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{int(height)}',
                        ha='center', va='bottom', fontsize=12)
            
            plt.title('Nombre d\'étudiants par niveau', fontsize=16)
            plt.xlabel('Niveau', fontsize=12)
            plt.ylabel('Nombre d\'étudiants', fontsize=12)
            plt.xticks(rotation=0)
            
        elif chart_type == 'genre_pie':
            # Vérification de l'existence de la colonne "Genre"
            if 'Genre' not in df.columns:
                return jsonify({"error": "Données de genre non disponibles"}), 400
                
            # Remplacer les valeurs nulles par une chaîne vide
            df['Genre'] = df['Genre'].fillna('')
            
            # Compter les genres
            masculin_count = (df['Genre'].str.lower() == 'masculin').sum()
            feminin_count = (df['Genre'].str.lower() == 'féminin').sum()
            
            # Créer le camembert
            plt.pie([masculin_count, feminin_count], 
                   labels=['Masculin', 'Féminin'],
                   autopct='%1.1f%%',
                   colors=['#3366cc', '#dc3912'],
                   startangle=90)
            plt.title('Répartition des étudiants par genre', fontsize=16)
            
        elif chart_type == 'etrangers_bar':
            # Vérification de l'existence des colonnes nécessaires
            if 'Etranger(ère)' not in df.columns or 'niveau' not in df.columns:
                return jsonify({"error": "Données d'étrangers ou de niveau non disponibles"}), 400
            
            # Remplacer les valeurs vides
            df['Etranger(ère)'] = df['Etranger(ère)'].fillna('')
            
            # Pour les valeurs vides, vérifier la nationalité
            mask_vide = df['Etranger(ère)'] == ''
            if 'Nationalité' in df.columns:
                df.loc[mask_vide, 'Etranger(ère)'] = df.loc[mask_vide, 'Nationalité'].apply(
                    lambda x: 'Non' if x == 'Française' else 'Oui' if x else 'Non'
                )
            else:
                df.loc[mask_vide, 'Etranger(ère)'] = 'Non'
            
            # Créer une colonne pour identifier les étrangers
            df['est_etranger'] = df['Etranger(ère)'].str.lower() == 'oui'
            
            # Grouper par niveau et calculer le taux d'étrangers
            etrangers_data = df.groupby('niveau').apply(
                lambda x: pd.Series({
                    'total': len(x),
                    'etrangers': x['est_etranger'].sum(),
                    'taux_etrangers': (x['est_etranger'].sum() / len(x) * 100) if len(x) > 0 else 0
                })
            ).reset_index()
            
            # Créer le graphique en barres
            bars = plt.bar(etrangers_data['niveau'], etrangers_data['taux_etrangers'], color='#3366cc')
            
            # Ajouter les valeurs sur les barres
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                        f'{height:.1f}%',
                        ha='center', va='bottom', fontsize=12)
            
            plt.title('Taux d\'étudiants étrangers par niveau', fontsize=16)
            plt.xlabel('Niveau', fontsize=12)
            plt.ylabel('Taux d\'étrangers (%)', fontsize=12)
            plt.xticks(rotation=0)
            plt.ylim(0, 100)  # Limiter l'axe y à 100%
            
        elif chart_type == 'evolution_line':
            # Vérification de l'existence des colonnes nécessaires
            if 'niveau' not in df.columns or 'annee' not in df.columns:
                return jsonify({"error": "Données de niveau ou d'année non disponibles"}), 400
            
            # Remplacer les valeurs manquantes
            if df['annee'].dtype == 'object':
                # Si annee est une chaîne de caractères, extraire l'année de début (ex: "2021-2022" -> "2021")
                df['annee_start'] = df['annee'].str.split('-').str[0]
            else:
                df['annee_start'] = df['annee']
            
            # Grouper par année et niveau
            evolution_data = df.groupby(['annee_start', 'niveau']).size().unstack(fill_value=0).reset_index()
            evolution_data = evolution_data.sort_values('annee_start')
            
            # Créer le graphique en ligne
            for col in evolution_data.columns[1:]:  # Ignorer la colonne annee_start
                plt.plot(evolution_data['annee_start'], evolution_data[col], marker='o', linewidth=2, label=col)
            
            plt.title('Évolution du nombre d\'étudiants par niveau et par année', fontsize=16)
            plt.xlabel('Année', fontsize=12)
            plt.ylabel('Nombre d\'étudiants', fontsize=12)
            plt.xticks(rotation=45)
            plt.legend(title='Niveau')
            plt.grid(True, linestyle='--', alpha=0.7)
            
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
        app.logger.error(f"Erreur lors de la génération du graphique: {str(e)}")
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
            # Log plus d'information sur le fichier
            print(f"Traitement du fichier: {file.filename}")
            
            # Récupérer des paramètres supplémentaires depuis le nom du fichier
            import re
            annee_match = re.search(r'(20\d{2})[-_](20\d{2})', file.filename)
            if annee_match:
                annee_debut = annee_match.group(1)
                annee_fin = annee_match.group(2)
            else:
                # Valeurs par défaut
                annee_debut = '2020'
                annee_fin = '2021'
                
            annee_academique = f"{annee_debut}-{annee_fin}"
            print(f"Année académique détectée: {annee_academique}")
            
            # Lecture du fichier
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:  # Excel
                df = pd.read_excel(file)
            
            print(f"Dimensions du DataFrame: {df.shape}")
            print("Colonnes dans le fichier:", df.columns.tolist())
            
            # Vérification des colonnes requises
            required_columns = ['code_ue', 'nom_matiere']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return jsonify({
                    "error": f"Format du fichier non reconnu. Colonnes essentielles manquantes: {', '.join(missing_columns)}",
                    "success": False
                }), 400
            
            # Information de débogage
            print("Valeurs de niveau:", df['niveau'].unique() if 'niveau' in df.columns else "Colonne niveau absente")
            print("Valeurs de semestre:", df['semestre'].unique() if 'semestre' in df.columns else "Colonne semestre absente")
            
            # Vérifier que les colonnes 'niveau' et 'semestre' sont présentes
            if 'niveau' not in df.columns:
                print("Colonne 'niveau' manquante, ajout d'une valeur par défaut 'FIE1'")
                df['niveau'] = 'FIE1'
            
            if 'semestre' not in df.columns:
                print("Colonne 'semestre' manquante, ajout d'une valeur par défaut 'S1'")
                df['semestre'] = 'S1'
            
            # Prétraitement - Convertir les valeurs non numériques en 0
            for col in ['cm_hm', 'cm_hp', 'cm_hr', 'td_hm', 'td_hp', 'td_hr', 'tp_hm', 'tp_hp', 'tp_hr']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # Prétraitement - Remplacer les NaN par des valeurs par défaut
            default_values = {
                'ects': 0,
                'intervenant': '',
                'cm_hm': 0, 'cm_hp': 0, 'cm_hr': 0,
                'td_hm': 0, 'td_hp': 0, 'td_hr': 0,
                'tp_hm': 0, 'tp_hp': 0, 'tp_hr': 0
            }
            
            for col, default_val in default_values.items():
                if col in df.columns:
                    df[col] = df[col].fillna(default_val)
                else:
                    df[col] = default_val
            
            # Traiter chaque ligne en respectant son niveau et semestre spécifiques
            records_to_insert = []
            matiere_count = 0
            
            # Grouper par niveau et semestre pour traiter chaque groupe séparément
            for _, group_df in df.groupby(['niveau', 'semestre']):
                # Pour chaque groupe niveau-semestre, traiter les UE
                ue_dict = {}
                current_ue = None
                
                # Obtenir le niveau et semestre de ce groupe
                niveau = str(group_df['niveau'].iloc[0]).strip()
                semestre = str(group_df['semestre'].iloc[0]).strip()
                
                print(f"Traitement du groupe: niveau={niveau}, semestre={semestre}")
                
                # Parcourir les lignes du groupe
                for index, row in group_df.iterrows():
                    # Extraire les valeurs
                    code_ue = str(row['code_ue']).strip() if not pd.isna(row['code_ue']) else ''
                    nom_matiere = str(row['nom_matiere']).strip() if not pd.isna(row['nom_matiere']) else 'Sans nom'
                    
                    # Debug
                    if index < 5:
                        print(f"Ligne {index}: code_ue='{code_ue}', nom_matiere='{nom_matiere}'")
                    
                    # Forcer la création d'une UE pour chaque ligne ayant un code_ue
                    if code_ue and not code_ue.isspace():
                        # Créer une clé unique qui inclut niveau et semestre
                        ue_key = f"{niveau}_{semestre}_{code_ue}"
                        
                        # Vérifier si cette UE existe déjà dans ce groupe
                        if ue_key not in ue_dict:
                            ue_dict[ue_key] = {
                                "code": code_ue,
                                "nom": nom_matiere,
                                "matieres": []
                            }
                        current_ue = ue_dict[ue_key]
                    
                    # Si pas de code_ue mais qu'on a un nom_matiere et une UE courante, c'est une matière de cette UE
                    if not code_ue and nom_matiere and current_ue:
                        # Traiter comme une matière de l'UE courante
                        pass
                    
                    # Si on a une UE courante, on peut ajouter une matière
                    if current_ue:
                        try:
                            # Convertir les valeurs en nombres avec gestion d'erreurs
                            def safe_convert(val, default=0):
                                try:
                                    if pd.isna(val):
                                        return default
                                    return float(val)
                                except (ValueError, TypeError):
                                    return default
                            
                            ects = safe_convert(row.get('ects', 0))
                            intervenant = str(row.get('intervenant', '')) if not pd.isna(row.get('intervenant', '')) else ''
                            
                            # Heures CM, TD, TP
                            cm_hm = safe_convert(row.get('cm_hm', 0))
                            cm_hp = safe_convert(row.get('cm_hp', 0))
                            cm_hr = safe_convert(row.get('cm_hr', 0))
                            
                            td_hm = safe_convert(row.get('td_hm', 0))
                            td_hp = safe_convert(row.get('td_hp', 0))
                            td_hr = safe_convert(row.get('td_hr', 0))
                            
                            tp_hm = safe_convert(row.get('tp_hm', 0))
                            tp_hp = safe_convert(row.get('tp_hp', 0))
                            tp_hr = safe_convert(row.get('tp_hr', 0))
                            
                            # Ajouter la matière même si les heures sont toutes à 0
                            matiere = {
                                "nom": nom_matiere if nom_matiere != current_ue["nom"] else f"{nom_matiere} (cours)",
                                "ects": ects,
                                "intervenant": intervenant,
                                "heures_cm": {
                                    "hm": cm_hm,
                                    "hp": cm_hp,
                                    "hr": cm_hr
                                },
                                "heures_td": {
                                    "hm": td_hm,
                                    "hp": td_hp,
                                    "hr": td_hr
                                },
                                "heures_tp": {
                                    "hm": tp_hm,
                                    "hp": tp_hp,
                                    "hr": tp_hr
                                }
                            }
                            current_ue["matieres"].append(matiere)
                            matiere_count += 1
                            
                        except Exception as e:
                            print(f"Erreur lors du traitement de la ligne {index}: {e}")
                
                # Préparer les documents pour MongoDB pour ce groupe
                for ue_key, ue_data in ue_dict.items():
                    # Extraire niveau et semestre de la clé
                    parts = ue_key.split('_', 2)  # Diviser en 3 parties: niveau, semestre, code_ue
                    record_niveau = parts[0]
                    record_semestre = parts[1]
                    
                    # Créer l'enregistrement
                    record = {
                        "annee_academique": annee_academique,
                        "annee_debut": int(annee_debut),
                        "annee_fin": int(annee_fin),
                        "niveau": record_niveau,
                        "semestre": record_semestre,
                        "unite_enseignement": ue_data,
                        "uploaded_by": current_user['username'],
                        "uploaded_at": datetime.utcnow()
                    }
                    records_to_insert.append(record)
            
            print(f"Total des matières traitées: {matiere_count}")
            print(f"Enregistrements à insérer: {len(records_to_insert)}")
            
            # MODIFICATION IMPORTANTE : Ne pas supprimer les données existantes
            # Au lieu de cela, vérifier pour chaque UE si elle existe déjà
            
            # Pour chaque enregistrement à insérer, vérifier s'il existe déjà
            inserted_count = 0
            updated_count = 0
            
            for record in records_to_insert:
                # Vérifier si cet enregistrement existe déjà (même UE, niveau, semestre, année)
                existing = heures_enseignement_collection.find_one({
                    "annee_academique": record["annee_academique"],
                    "niveau": record["niveau"],
                    "semestre": record["semestre"],
                    "unite_enseignement.code": record["unite_enseignement"]["code"]
                })
                
                if existing:
                    # Si l'enregistrement existe, générer un nouveau code UE unique
                    original_code = record["unite_enseignement"]["code"]
                    # Ajouter un horodatage pour rendre le code unique
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    new_code = f"{original_code}_{timestamp}"
                    
                    # Mettre à jour le code UE dans l'enregistrement
                    record["unite_enseignement"]["code"] = new_code
                    print(f"UE existante trouvée: {original_code}, nouveau code généré: {new_code}")
                    
                    # Insérer comme nouvel enregistrement
                    heures_enseignement_collection.insert_one(record)
                    inserted_count += 1
                else:
                    # Si l'enregistrement n'existe pas, l'insérer directement
                    heures_enseignement_collection.insert_one(record)
                    inserted_count += 1
            
            print(f"Enregistrements insérés: {inserted_count}")
            
            return jsonify({
                "message": f"Données d'heures d'enseignement importées avec succès. {inserted_count} enregistrements insérés, aucune donnée supprimée.",
                "records_inserted": inserted_count,
                "success": True
            }), 200
                
        except Exception as e:
            import traceback
            traceback_str = traceback.format_exc()
            print(f"Erreur détaillée: {traceback_str}")
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
        intervenant = request.args.get('intervenant')
        
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

        if intervenant:
            # Cette partie est délicate car nous devons filtrer à l'intérieur d'un tableau
            filter_query["unite_enseignement.matieres.intervenant"] = intervenant
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
        intervenant = request.args.get('intervenant')
        # Construire le filtre en fonction des paramètres fournis
        filter_query = {}
        
        if annee_debut and annee_fin:
            filter_query["annee_academique"] = f"{annee_debut}-{annee_fin}"
        elif annee_debut:
            filter_query["annee_debut"] = int(annee_debut)
        
        if niveau:
            filter_query["niveau"] = niveau

        if intervenant:
            # Cette partie est délicate car nous devons filtrer à l'intérieur d'un tableau
            filter_query["unite_enseignement.matieres.intervenant"] = intervenant
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

@app.route('/api/heures-enseignement/graph-data', methods=['GET'])
@token_required
def get_heures_enseignement_graph_data(current_user):
    """Endpoint pour récupérer les données formatées pour les graphiques"""
    try:
        # Paramètres de filtrage
        annee_debut = request.args.get('annee_debut')
        annee_fin = request.args.get('annee_fin')
        niveau = request.args.get('niveau')
        semestre = request.args.get('semestre')
        intervenant = request.args.get('intervenant')
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
            
        if intervenant:
            # Cette partie est délicate car nous devons filtrer à l'intérieur d'un tableau
            filter_query["unite_enseignement.matieres.intervenant"] = intervenant
        # Récupérer les données
        data = list(heures_enseignement_collection.find(filter_query, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée trouvée avec ces filtres"}), 404
        
        # Préparation des données pour les graphiques
        graph_data = {
            "pie_chart": prepare_pie_chart_data(data),
            "line_chart": prepare_line_chart_data(data),
            "bar_chart_niveau": prepare_bar_chart_niveau_data(data),
            "bar_chart_semestre": prepare_bar_chart_semestre_data(data)
        }
        
        return jsonify(graph_data), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500

def prepare_pie_chart_data(data):
    """Prépare les données pour le graphique camembert des types d'heures"""
    total_cm = 0
    total_td = 0
    total_tp = 0
    
    for record in data:
        ue = record.get('unite_enseignement', {})
        for matiere in ue.get('matieres', []):
            # Additionner les heures maquette (hm) de chaque type
            total_cm += matiere.get('heures_cm', {}).get('hm', 0)
            total_td += matiere.get('heures_td', {}).get('hm', 0)
            total_tp += matiere.get('heures_tp', {}).get('hm', 0)
    
    return {
        "labels": ["CM", "TD", "TP"],
        "data": [total_cm, total_td, total_tp]
    }

def prepare_line_chart_data(data):
    """Prépare les données pour le graphique d'évolution des heures par année"""
    # Regrouper les données par année académique
    annees = {}
    
    for record in data:
        annee = record.get('annee_academique')
        if not annee in annees:
            annees[annee] = {'cm': 0, 'td': 0, 'tp': 0}
        
        ue = record.get('unite_enseignement', {})
        for matiere in ue.get('matieres', []):
            annees[annee]['cm'] += matiere.get('heures_cm', {}).get('hm', 0)
            annees[annee]['td'] += matiere.get('heures_td', {}).get('hm', 0)
            annees[annee]['tp'] += matiere.get('heures_tp', {}).get('hm', 0)
    
    # Trier les années
    sorted_annees = sorted(annees.keys())
    
    return {
        "labels": sorted_annees,
        "datasets": [
            {
                "label": "CM",
                "data": [annees[annee]['cm'] for annee in sorted_annees]
            },
            {
                "label": "TD",
                "data": [annees[annee]['td'] for annee in sorted_annees]
            },
            {
                "label": "TP",
                "data": [annees[annee]['tp'] for annee in sorted_annees]
            }
        ]
    }

def prepare_bar_chart_niveau_data(data):
    """Prépare les données pour le graphique à barres des heures par niveau"""
    # Regrouper les données par niveau
    niveaux = {}
    
    for record in data:
        niveau = record.get('niveau')
        if not niveau in niveaux:
            niveaux[niveau] = {'cm': 0, 'td': 0, 'tp': 0}
        
        ue = record.get('unite_enseignement', {})
        for matiere in ue.get('matieres', []):
            niveaux[niveau]['cm'] += matiere.get('heures_cm', {}).get('hm', 0)
            niveaux[niveau]['td'] += matiere.get('heures_td', {}).get('hm', 0)
            niveaux[niveau]['tp'] += matiere.get('heures_tp', {}).get('hm', 0)
    
    # Obtenir la liste des niveaux
    niveau_labels = list(niveaux.keys())
    
    return {
        "labels": niveau_labels,
        "datasets": [
            {
                "label": "CM",
                "data": [niveaux[niveau]['cm'] for niveau in niveau_labels]
            },
            {
                "label": "TD",
                "data": [niveaux[niveau]['td'] for niveau in niveau_labels]
            },
            {
                "label": "TP",
                "data": [niveaux[niveau]['tp'] for niveau in niveau_labels]
            }
        ]
    }

def prepare_bar_chart_semestre_data(data):
    """Prépare les données pour le graphique à barres des heures par semestre"""
    # Regrouper les données par semestre
    semestres = {}
    
    for record in data:
        semestre = record.get('semestre')
        if not semestre in semestres:
            semestres[semestre] = {'cm': 0, 'td': 0, 'tp': 0}
        
        ue = record.get('unite_enseignement', {})
        for matiere in ue.get('matieres', []):
            semestres[semestre]['cm'] += matiere.get('heures_cm', {}).get('hm', 0)
            semestres[semestre]['td'] += matiere.get('heures_td', {}).get('hm', 0)
            semestres[semestre]['tp'] += matiere.get('heures_tp', {}).get('hm', 0)
    
    # Trier les semestres
    semestre_labels = sorted(semestres.keys())
    
    return {
        "labels": semestre_labels,
        "datasets": [
            {
                "label": "CM",
                "data": [semestres[semestre]['cm'] for semestre in semestre_labels]
            },
            {
                "label": "TD",
                "data": [semestres[semestre]['td'] for semestre in semestre_labels]
            },
            {
                "label": "TP",
                "data": [semestres[semestre]['tp'] for semestre in semestre_labels]
            }
        ]
    }

@app.route('/api/references/intervenants', methods=['GET'])
@token_required
def get_intervenants(current_user):
    """Récupérer la liste des intervenants disponibles"""
    try:
        # Utiliser une agrégation MongoDB pour extraire tous les intervenants uniques
        pipeline = [
            {"$unwind": "$unite_enseignement.matieres"},  # Décomposer le tableau des matières
            {"$group": {"_id": "$unite_enseignement.matieres.intervenant"}},  # Grouper par intervenant
            {"$match": {"_id": {"$ne": ""}}},  # Exclure les valeurs vides
            {"$sort": {"_id": 1}}  # Trier par ordre alphabétique
        ]
        
        result = list(heures_enseignement_collection.aggregate(pipeline))
        
        intervenants = [item["_id"] for item in result if item["_id"]]
        
        return jsonify(intervenants), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des intervenants: {str(e)}"}), 500
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
    """Endpoint pour uploader des données RSE (supporte CSV et JSON)"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'upload' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
    
    # Vérifier s'il s'agit d'une requête JSON (bulk_add)
    if request.is_json:
        data = request.get_json()
        
        if not data or 'data' not in data:
            return jsonify({"error": "Données manquantes ou format incorrect"}), 400
        
        records = data['data']
        
        if not records or not isinstance(records, list):
            return jsonify({"error": "Format de données invalide - tableau attendu"}), 400
        
        try:
            # Traitement des enregistrements
            for i, record in enumerate(records):
                # Ajout d'un ID unique s'il n'existe pas
                if 'id' not in record:
                    record['id'] = f"rse_{int(datetime.utcnow().timestamp())}_{i}"
                
                # Métadonnées
                record['uploaded_by'] = current_user['username']
                record['uploaded_at'] = datetime.utcnow()
                record['created_by'] = current_user['username']
                record['created_at'] = datetime.utcnow()
                record['updated_by'] = current_user['username']
                record['updated_at'] = datetime.utcnow()
                
                # S'assurer que les champs numériques sont des nombres
                record['annee'] = int(record.get('annee', datetime.utcnow().year))
                record['heures_cm'] = int(record.get('heures_cm', 0))
                record['heures_td'] = int(record.get('heures_td', 0))
                record['heures_tp'] = int(record.get('heures_tp', 0))
                
                # Traitement des champs supplémentaires (heure1, heure2, heure3, heure4)
                for hour_field in ['heure1', 'heure2', 'heure3', 'heure4']:
                    if hour_field in record:
                        record[hour_field] = int(record.get(hour_field, 0))
                
                # Recalculer le total des heures si nécessaire
                record['total_heures'] = record['heures_cm'] + record['heures_td'] + record['heures_tp']
            
            # Insertion dans la base de données
            result = rse_collection.insert_many(records)
            
            return jsonify({
                "message": "Données RSE ajoutées avec succès",
                "records_inserted": len(result.inserted_ids),
                "success": True
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"Erreur lors de l'ajout des données RSE: {str(e)}"}), 500
    
    # Sinon, c'est un upload de fichier CSV comme avant
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier n'a été sélectionné"}), 400
    if file and file.filename.endswith('.csv'):
        try:
            # Lecture du fichier CSV avec pandas
            df = pd.read_csv(file, encoding='utf-8')
            
            # Vérifier que le fichier correspond au format attendu
            expected_columns = ['promotion_semestre', 'activite', 'cm_maquette', 'td_maquette', 
                              'cm_hors_maquette', 'td1', 'td2', 'td3', 'td4', 'td5', 'total_heures']
            
            missing_columns = [col for col in expected_columns if col not in df.columns]
            if missing_columns:
                # Si certaines colonnes manquent, vérifier si c'est un format alternatif
                # Pour le format standard RSE
                alt_columns = ['annee', 'promotion', 'semestre', 'type_activite', 'heures_cm', 'heures_td', 'heures_tp']
                alt_missing = [col for col in alt_columns if col not in df.columns]
                
                if alt_missing:
                    return jsonify({
                        "error": f"Format de fichier non reconnu. Colonnes manquantes: {', '.join(missing_columns)}"
                    }), 400
                else:
                    # C'est le format standard RSE, on peut procéder directement
                    return process_standard_rse_format(df, current_user)
            
            # C'est le format spécifique avec promotion_semestre, etc.
            # Transformation en format RSE standard
            records = []
            
            for _, row in df.iterrows():
                # Extraire promotion et semestre de promotion_semestre
                promotion_semestre = str(row.get('promotion_semestre', ''))
                
                # Pattern attendu: FIEx-Sy
                parts = promotion_semestre.split('-')
                if len(parts) == 2:
                    promotion = parts[0].strip()
                    semestre = parts[1].strip()
                else:
                    # Si format incorrect, utiliser des valeurs par défaut
                    promotion = promotion_semestre
                    semestre = "S1"  # Valeur par défaut
                
                # Déterminer l'année en fonction de la promotion (approximation)
                current_year = datetime.utcnow().year
                annee = current_year
                
                # Extraire les heures
                heures_cm = parse_numeric_value(row.get('cm_maquette', 0)) + parse_numeric_value(row.get('cm_hors_maquette', 0))
                heures_td = sum([
                    parse_numeric_value(row.get('td_maquette', 0)),
                    parse_numeric_value(row.get('td1', 0)),
                    parse_numeric_value(row.get('td2', 0))
                ])
                heures_tp = sum([
                    parse_numeric_value(row.get('td3', 0)),
                    parse_numeric_value(row.get('td4', 0)),
                    parse_numeric_value(row.get('td5', 0))
                ])
                
                # Calculer le total ou utiliser celui fourni
                total_heures = parse_numeric_value(row.get('total_heures', 0))
                if total_heures == 0:
                    total_heures = heures_cm + heures_td + heures_tp
                
                # Créer l'enregistrement au format standard RSE
                record = {
                    'id': f"rse_{int(datetime.utcnow().timestamp())}_{len(records)}",
                    'annee': annee,
                    'promotion': promotion,
                    'semestre': semestre,
                    'type_activite': str(row.get('activite', '')),
                    'heures_cm': int(heures_cm),
                    'heures_td': int(heures_td),
                    'heures_tp': int(heures_tp),
                    'total_heures': int(total_heures),
                    'uploaded_by': current_user['username'],
                    'uploaded_at': datetime.utcnow(),
                    'created_by': current_user['username'],
                    'created_at': datetime.utcnow(),
                    'updated_by': current_user['username'],
                    'updated_at': datetime.utcnow()
                }
                
                records.append(record)
            
            # Insertion des nouvelles données
            if records:
                result = rse_collection.insert_many(records)
                
                return jsonify({
                    "message": "Fichier CSV RSE traité avec succès", 
                    "records_inserted": len(result.inserted_ids),
                    "success": True
                }), 200
            else:
                return jsonify({
                    "warning": "Aucune donnée valide trouvée dans le fichier CSV RSE",
                    "success": False
                }), 400
                
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier CSV RSE: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

def process_standard_rse_format(df, current_user):
    """Traite un fichier CSV au format RSE standard"""
    try:
        # Conversion du DataFrame en liste de dictionnaires pour MongoDB
        records = df.to_dict('records')
        
        # Ajout de métadonnées et calculs
        for i, record in enumerate(records):
            record['id'] = f"rse_{int(datetime.utcnow().timestamp())}_{i}"
            
            # Convertir les types numériques
            record['annee'] = int(record.get('annee', datetime.utcnow().year))
            record['heures_cm'] = int(record.get('heures_cm', 0))
            record['heures_td'] = int(record.get('heures_td', 0))
            record['heures_tp'] = int(record.get('heures_tp', 0))
            
            # Calculer le total
            record['total_heures'] = record['heures_cm'] + record['heures_td'] + record['heures_tp']
            
            # Métadonnées
            record['uploaded_by'] = current_user['username']
            record['uploaded_at'] = datetime.utcnow()
            record['created_by'] = current_user['username']
            record['created_at'] = datetime.utcnow()
            record['updated_by'] = current_user['username']
            record['updated_at'] = datetime.utcnow()
        
        # Insertion des nouvelles données
        result = rse_collection.insert_many(records)
        
        return jsonify({
            "message": "Fichier CSV RSE traité avec succès", 
            "records_inserted": len(result.inserted_ids),
            "success": True
        }), 200
    except Exception as e:
        return jsonify({"error": f"Erreur lors du traitement du fichier CSV RSE standard: {str(e)}"}), 500

def parse_numeric_value(value):
    """Convertit une valeur en nombre, gère les cas particuliers"""
    if value is None:
        return 0
    
    if isinstance(value, (int, float)):
        return value
    
    try:
        # Supprimer les caractères non numériques sauf le point décimal
        cleaned_value = ''.join(c for c in str(value) if c.isdigit() or c == '.')
        if cleaned_value:
            return float(cleaned_value)
        return 0
    except (ValueError, TypeError):
        return 0
    
@app.route('/api/rse/bulk_add', methods=['POST'])
@token_required
def rse_bulk_add(current_user):
    """Endpoint pour l'ajout en masse de données RSE à partir du CSV transformé"""
    # Vérification des permissions
    user_role = current_user['role']
    if 'upload' not in PERMISSIONS.get(user_role, []):
        return jsonify({"error": "Permissions insuffisantes"}), 403
    
    # Récupérer les données JSON
    data = request.get_json()
    
    if not data or 'data' not in data:
        return jsonify({"error": "Données manquantes ou format incorrect"}), 400
    
    records = data['data']
    
    if not records or not isinstance(records, list):
        return jsonify({"error": "Format de données invalide - tableau attendu"}), 400
    
    try:
        # Traitement des enregistrements
        for i, record in enumerate(records):
            # Ajout d'un ID unique s'il n'existe pas
            if 'id' not in record:
                record['id'] = f"rse_{int(datetime.utcnow().timestamp())}_{i}"
            
            # Métadonnées
            record['uploaded_by'] = current_user['username']
            record['uploaded_at'] = datetime.utcnow()
            record['created_by'] = current_user['username']
            record['created_at'] = datetime.utcnow()
            record['updated_by'] = current_user['username']
            record['updated_at'] = datetime.utcnow()
        
        # Insertion dans la base de données
        result = rse_collection.insert_many(records)
        
        return jsonify({
            "message": "Données RSE ajoutées avec succès",
            "records_inserted": len(result.inserted_ids),
            "success": True
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'ajout des données RSE: {str(e)}"}), 500

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



######################### Routes pour ARION ###################################
@app.route('/api/arion/data', methods=['GET'])
def get_arion_data():
    """Endpoint pour récupérer les données ARION"""
    try:
        # Paramètres de filtrage optionnels
        arion_id = request.args.get('id')
        annee = request.args.get('annee')
        formateur = request.args.get('formateur')
        statut = request.args.get('statut')
        
        # Construire le filtre en fonction des paramètres fournis
        filter_query = {}
        
        if arion_id:
            filter_query["id"] = arion_id
        if annee:
            filter_query["annee"] = annee
        if formateur:
            filter_query["formateur"] = {"$regex": formateur, "$options": "i"}
        if statut:
            filter_query["statut"] = statut
        
        # Récupérer les données avec tri par date décroissante
        cursor = arion_collection.find(filter_query, {'_id': 0}).sort([('annee', -1), ('date', -1)])
        
        # Convertir le curseur en liste et nettoyer les données
        data = list(cursor)
        
        # Remplacer explicitement les valeurs NaN, None, etc. par null pour JSON
        clean_data = []
        for item in data:
            clean_item = {}
            for key, value in item.items():
                # Convertir les valeurs problématiques en None pour JSON
                if isinstance(value, float) and math.isnan(value):
                    clean_item[key] = None
                else:
                    clean_item[key] = value
            clean_data.append(clean_item)
        
        return jsonify(clean_data), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données ARION: {str(e)}"}), 500
@app.route('/api/arion/add', methods=['POST'])
def add_arion_data():
    """Endpoint pour ajouter/modifier des données ARION"""
    data = request.json
    
    if not data:
        return jsonify({"error": "Données manquantes"}), 400
    
    # Validation des champs obligatoires
    required_fields = ['annee', 'formateur', 'statut', 'groupe', 'activite', 
                      'code_y', 'niveau', 'date', 'duree']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return jsonify({"error": f"Champs manquants: {', '.join(missing_fields)}"}), 400
    
    try:
        # Vérifier si c'est une mise à jour ou un ajout
        is_update = 'id' in data and data['id']
        
        # Conversion des types
        data['duree'] = float(data['duree'])
        
        # Ajout de métadonnées
        if is_update:
            data['updated_by'] = 'admin'  # Valeur par défaut
            data['updated_at'] = datetime.utcnow()
        else:
            data['id'] = f"arion_{int(datetime.utcnow().timestamp())}"
            data['created_by'] = 'admin'  # Valeur par défaut
            data['created_at'] = datetime.utcnow()
        
        # Mise à jour ou insertion
        if is_update:
            result = arion_collection.update_one(
                {"id": data['id']}, 
                {"$set": data}
            )
            
            if result.matched_count == 0:
                return jsonify({"error": "Aucune donnée trouvée avec cet ID"}), 404
                
            message = "Données ARION mises à jour avec succès"
        else:
            result = arion_collection.insert_one(data)
            message = "Nouvelles données ARION ajoutées avec succès"
            
        return jsonify({"message": message, "success": True, "id": data['id']}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'ajout/modification des données ARION: {str(e)}"}), 500

@app.route('/api/arion/delete/<string:arion_id>', methods=['DELETE'])
def delete_arion_data(arion_id):
    """Endpoint pour supprimer des données ARION"""
    try:
        # Suppression des données
        result = arion_collection.delete_one({"id": arion_id})
        
        if result.deleted_count == 0:
            return jsonify({"error": f"Aucune donnée ARION trouvée avec l'ID {arion_id}"}), 404
            
        return jsonify({"message": "Données ARION supprimées avec succès", "success": True}), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la suppression des données ARION: {str(e)}"}), 500

@app.route('/api/arion/upload', methods=['POST'])
def upload_arion_csv():
    """Endpoint pour importer un fichier CSV de données ARION"""
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier n'a été sélectionné"}), 400
    
    if file and file.filename.endswith('.csv'):
        try:
            # Récupérer l'année par défaut si spécifiée
            default_annee = request.form.get('annee_import', '')
            
            # Lecture du fichier CSV avec pandas
            # Utilisation de paramètres spécifiques pour gérer les valeurs NaN
            df = pd.read_csv(
                file,
                na_values=['', 'NA', 'N/A', 'nan', 'NaN', 'None', 'none'],  # Valeurs considérées comme NaN
                keep_default_na=True  # Conserver les valeurs NaN par défaut
            )
            
            # Validation des colonnes minimales requises
            required_columns = ['activite', 'groupe', 'code_y', 'niveau', 'date', 'duree']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return jsonify({
                    "error": f"Colonnes manquantes dans le CSV: {', '.join(missing_columns)}"
                }), 400
            
            # Ajouter colonne annee si non présente
            if 'annee' not in df.columns and default_annee:
                df['annee'] = default_annee
            
            # Vérifier que toutes les lignes ont une année
            if 'annee' not in df.columns or df['annee'].isnull().any():
                if not default_annee:
                    return jsonify({
                        "error": "Certaines lignes n'ont pas d'année spécifiée et aucune année par défaut n'a été fournie"
                    }), 400
                else:
                    # Appliquer l'année par défaut aux lignes sans année
                    if 'annee' in df.columns:
                        df['annee'] = df['annee'].fillna(default_annee)
                    else:
                        df['annee'] = default_annee
            
            # S'assurer que toutes les colonnes attendues existent, même vides
            for col in ['formateur', 'statut', 'lieu', 'intervenant']:
                if col not in df.columns:
                    df[col] = None
            
            # Conversion du DataFrame en liste de dictionnaires pour MongoDB
            # Remplacement explicite des valeurs NaN par None pour MongoDB
            df = df.replace({pd.NA: None})
            records = df.where(pd.notnull(df), None).to_dict('records')
            
            # Ajout de métadonnées et identifiants uniques
            timestamp = int(datetime.utcnow().timestamp())
            for i, record in enumerate(records):
                record['id'] = f"arion_csv_{timestamp}_{i}"
                record['uploaded_by'] = 'admin'  # Valeur par défaut
                record['uploaded_at'] = datetime.utcnow()
                record['created_by'] = 'admin'  # Valeur par défaut
                record['created_at'] = datetime.utcnow()
                
                # Conversion de la durée en nombre si possible
                if 'duree' in record and record['duree'] is not None:
                    try:
                        record['duree'] = float(record['duree'])
                    except (ValueError, TypeError):
                        record['duree'] = 0.0
            
            # Insertion des données
            if records:
                result = arion_collection.insert_many(records)
                
                return jsonify({
                    "message": "Importation CSV réussie", 
                    "records_inserted": len(result.inserted_ids),
                    "success": True
                }), 200
            else:
                return jsonify({"warning": "Aucune donnée trouvée dans le fichier CSV", "success": False}), 400
                
        except Exception as e:
            return jsonify({"error": f"Erreur lors du traitement du fichier CSV: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

@app.route('/api/arion/stats', methods=['GET'])
@token_required
def get_arion_stats():
    """Endpoint pour récupérer les statistiques ARION"""
    try:
        data = list(arion_collection.find({}, {'_id': 0}))
        
        if not data:
            return jsonify({"error": "Aucune donnée ARION trouvée"}), 404
        
        # Convertir en DataFrame pandas pour faciliter les calculs
        df = pd.DataFrame(data)
        
        # Calculer les statistiques
        stats = {
            "summary": {
                "total_activites": len(df),
                "total_duree": round(float(df['duree'].sum()), 1),
                "formateurs_count": len(df['formateur'].unique()),
                "niveaux_count": len(df['niveau'].unique()) if 'niveau' in df.columns else 0
            }
        }
        
        # Statistiques par année
        stats_par_annee = {}
        if 'annee' in df.columns:
            for annee in df['annee'].unique():
                annee_df = df[df['annee'] == annee]
                stats_par_annee[annee] = {
                    'count': len(annee_df),
                    'duree_totale': round(float(annee_df['duree'].sum()), 1)
                }
        
        # Préparation des données pour les graphiques
        graphiques = {
            'annees': {
                'labels': list(stats_par_annee.keys()),
                'values': [stats_par_annee[a]['count'] for a in stats_par_annee]
            }
        }
        
        # Evolution mensuelle (pour les 12 derniers mois)
        evolution_mensuelle = {}
        if 'date' in df.columns:
            # Convertir la colonne date en datetime si ce n'est pas déjà fait
            if df['date'].dtype != 'datetime64[ns]':
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
            
            # Filtrer les dates valides
            date_df = df.dropna(subset=['date'])
            if not date_df.empty:
                # Extraire le mois et l'année
                date_df['mois'] = date_df['date'].dt.strftime('%Y-%m')
                
                # Regrouper par mois
                monthly_counts = date_df.groupby('mois').size()
                
                # Sélectionner les 12 derniers mois avec des données
                last_months = sorted(monthly_counts.index)[-12:] if len(monthly_counts) > 0 else []
                
                for month in last_months:
                    evolution_mensuelle[month] = int(monthly_counts.get(month, 0))
                
                graphiques['evolution_mensuelle'] = {
                    'labels': list(evolution_mensuelle.keys()),
                    'values': list(evolution_mensuelle.values())
                }
        
        # Ajouter les graphiques aux statistiques
        stats['graphiques'] = graphiques
        
        return jsonify(stats), 200
        
    except Exception as e:
        return jsonify({"error": f"Erreur lors du calcul des statistiques ARION: {str(e)}"}), 500

@app.route('/api/arion/status-stats', methods=['GET'])
@token_required
def get_arion_status_stats(current_user):
    try:
        # Vérifier si des données existent
        count = db.arion_data.count_documents({})
        app.logger.info(f"Nombre total de documents dans arion_data: {count}")
        
        if count == 0:
            # Si aucune donnée, retourner un tableau vide mais sans données fictives
            return jsonify({
                "success": True,
                "status_stats": {
                    "labels": [],
                    "values": []
                },
                "message": "Aucune donnée trouvée dans la base de données"
            })
        
        # Faire une requête simple pour voir les différents statuts
        statuts_disponibles = db.arion_data.distinct("statut")
        app.logger.info(f"Statuts disponibles: {statuts_disponibles}")
        
        # Agrégation pour compter par statut
        pipeline = [
            {"$group": {"_id": "$statut", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(db.arion_data.aggregate(pipeline))
        app.logger.info(f"Résultat de l'agrégation: {result}")
        
        # Traiter les résultats
        statuses = {}
        for item in result:
            # Si le statut est null ou vide, l'étiqueter comme "Non spécifié"
            status = item["_id"] if item["_id"] else "Non spécifié"
            count = item["count"]
            statuses[status] = count
        
        # Créer les tableaux pour l'histogramme
        labels = list(statuses.keys())
        values = list(statuses.values())
        
        # Enregistrer les valeurs finales pour le débogage
        app.logger.info(f"Labels: {labels}")
        app.logger.info(f"Values: {values}")
        
        return jsonify({
            "success": True,
            "status_stats": {
                "labels": labels,
                "values": values
            }
        })
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des statistiques par statut: {str(e)}")
        # En cas d'erreur, retourner un message clair mais pas de données fictives
        return jsonify({
            "success": False,
            "error": str(e),
            "message": "Une erreur s'est produite lors de la récupération des données"
        }), 500

@app.route('/api/arion/monthly_stats', methods=['GET'])
@token_required
def get_arion_monthly_stats():
    try:
        # Récupérer le paramètre d'année optionnel
        selected_year = request.args.get('year', None)
        
        # Connexion à MongoDB
        client = MongoClient(app.config['MONGO_URI'])
        db = client[app.config['MONGO_DBNAME']]
        collection = db.arion_data
        
        # Initialiser les compteurs pour chaque mois
        months = range(1, 13)
        monthly_counts = {month: 0 for month in months}
        
        # Construire le pipeline d'agrégation
        pipeline = []
        
        # Filtrer par année si spécifiée
        if selected_year:
            # Filtrer les enregistrements dont l'année (dans le champ annee) contient l'année sélectionnée
            # ou dont la date est dans l'année sélectionnée
            pipeline.append({
                "$match": {
                    "$or": [
                        {"annee": {"$regex": f"^{selected_year}"}},
                        {"date": {"$regex": f"^{selected_year}"}}
                    ]
                }
            })
        
        # Grouper par mois et compter les activités
        pipeline.extend([
            {
                "$addFields": {
                    "month": {
                        "$cond": {
                            "if": {"$ne": ["$date", None]},
                            "then": {
                                "$month": {
                                    "$dateFromString": {
                                        "dateString": "$date",
                                        "format": "%Y-%m-%d"
                                    }
                                }
                            },
                            "else": None
                        }
                    }
                }
            },
            {
                "$match": {
                    "month": {"$ne": None}
                }
            },
            {
                "$group": {
                    "_id": "$month",
                    "count": {"$sum": 1}
                }
            }
        ])
        
        # Exécuter l'agrégation
        results = list(collection.aggregate(pipeline))
        
        # Remplir les compteurs avec les résultats
        for result in results:
            month = result["_id"]
            if month in monthly_counts:
                monthly_counts[month] = result["count"]
        
        # Préparer les données pour le graphique
        month_names = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        values = [monthly_counts[month] for month in months]
        
        return jsonify({
            "labels": month_names,
            "values": values
        })
    
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des statistiques mensuelles: {str(e)}")
        return jsonify({"error": "Erreur lors de la récupération des statistiques mensuelles"}), 500
######################### Routes pour VACATAIRES ###################################
@app.route('/api/vacataire/add', methods=['POST'])
@token_required
def add_vacataire(current_user):
    """Endpoint pour ajouter un vacataire manuellement"""
    try:
        data = request.json
        
        # Valider les données requises
        required_fields = ['nom', 'prenom', 'email']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"Le champ {field} est requis"}), 400
        
        # Générer un ID unique si non fourni
        if not data.get('id'):
            data['id'] = str(uuid.uuid4())
            
        # Ajouter la date de création
        data['date_creation'] = datetime.now().isoformat()
        data['cree_par'] = current_user.get('username', 'system')
        
        # Insérer dans la collection
        result = vacataire_collection.insert_one(data)
        
        if result.inserted_id:
            return jsonify({"message": "Vacataire ajouté avec succès", "id": data['id']}), 201
        else:
            return jsonify({"error": "Erreur lors de l'ajout du vacataire"}), 500
            
    except Exception as e:
        app.logger.error(f"Erreur lors de l'ajout d'un vacataire: {str(e)}")
        return jsonify({"error": f"Erreur lors de l'ajout: {str(e)}"}), 500
@app.route('/api/vacataire/data', methods=['GET'])
@token_required
def get_vacataire_data(current_user):
    """Endpoint pour récupérer les données des vacataires"""
    try:
        # Récupérer tous les documents de la collection vacataire
        cursor = vacataire_collection.find({}, {'_id': 0})
        
        # Convertir le curseur en liste
        vacataires = list(cursor)
        
        # Nettoyer les données (remplacer None et NaN par des chaînes vides)
        for doc in vacataires:
            for key, value in doc.items():
                if value is None or (isinstance(value, float) and math.isnan(value)):
                    doc[key] = ""
        
        return jsonify(vacataires), 200
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des données vacataires: {str(e)}")
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500
    
@app.route('/api/vacataire/upload-csv', methods=['POST'])
@token_required
def upload_vacataire_csv(current_user):
    """Endpoint pour uploader un fichier CSV de vacataires"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Aucun fichier n'a été sélectionné"}), 400
            
        if file and file.filename.endswith('.csv'):
            # Lire le contenu du fichier
            content = file.read().decode('utf-8')
            
            try:
                # Utiliser pandas pour lire le CSV avec des options tolérantes aux erreurs
                df = pd.read_csv(io.StringIO(content), on_bad_lines='skip', sep=None, engine='python')
                
                app.logger.info(f"Colonnes détectées dans le CSV: {df.columns.tolist()}")
                
                # Préparer les données pour insertion exactement comme elles sont
                records = []
                for idx, row in df.iterrows():
                    # Créer un dictionnaire avec toutes les colonnes du CSV
                    record = {}
                    
                    # Parcourir toutes les colonnes et ajouter leurs valeurs
                    for col in df.columns:
                        if not pd.isna(row[col]):
                            record[col] = str(row[col])
                        else:
                            record[col] = ""  # Valeur vide pour les champs NA/NaN
                    
                    # Ajouter un ID unique s'il n'existe pas
                    if 'id' not in record:
                        record['id'] = str(uuid.uuid4())
                    
                    # Ajouter les métadonnées de base
                    record['date_creation'] = datetime.now().isoformat()
                    record['cree_par'] = current_user.get('username', 'system')
                    
                    records.append(record)
                
                # Insérer les données dans MongoDB exactement comme elles sont
                if records:
                    result = vacataire_collection.insert_many(records)
                    app.logger.info(f"Import CSV réussi: {len(result.inserted_ids)} enregistrements insérés")
                    return jsonify({
                        "message": "Import CSV réussi",
                        "records_inserted": len(result.inserted_ids)
                    }), 200
                else:
                    return jsonify({"message": "Aucun enregistrement à importer"}), 200
                    
            except Exception as e:
                app.logger.error(f"Erreur lors du traitement du CSV: {str(e)}")
                
                # Essayer avec une approche plus simple si pandas échoue
                try:
                    app.logger.info("Tentative avec une approche plus simple...")
                    
                    # Lire les lignes du fichier
                    lines = content.strip().split('\n')
                    
                    if not lines:
                        return jsonify({"error": "Le fichier CSV est vide"}), 400
                    
                    # Traiter manuellement le CSV
                    records = []
                    
                    # Détecter le séparateur (virgule, point-virgule, tabulation)
                    sep = ','  # Séparateur par défaut
                    for potential_sep in [',', ';', '\t']:
                        if potential_sep in lines[0]:
                            sep = potential_sep
                            app.logger.info(f"Séparateur détecté: {sep}")
                            break
                    
                    # Extraire les en-têtes
                    headers = [h.strip() for h in lines[0].split(sep)]
                    
                    # Créer un enregistrement pour chaque ligne de données
                    for line in lines[1:]:
                        if not line.strip():
                            continue  # Ignorer les lignes vides
                            
                        # Initialiser l'enregistrement avec l'ID et les métadonnées
                        record = {
                            'id': str(uuid.uuid4()),
                            'date_creation': datetime.now().isoformat(),
                            'cree_par': current_user.get('username', 'system')
                        }
                        
                        # Remplir avec les valeurs disponibles
                        values = line.split(sep)
                        for i, val in enumerate(values):
                            if i < len(headers):
                                header = headers[i].strip()
                                if header:  # S'assurer que l'en-tête n'est pas vide
                                    record[header] = val.strip()
                        
                        records.append(record)
                    
                    # Insérer les données dans MongoDB
                    if records:
                        result = vacataire_collection.insert_many(records)
                        app.logger.info(f"Import CSV réussi (méthode alternative): {len(result.inserted_ids)} enregistrements insérés")
                        return jsonify({
                            "message": "Import CSV réussi",
                            "records_inserted": len(result.inserted_ids)
                        }), 200
                    else:
                        return jsonify({"message": "Aucun enregistrement à importer"}), 200
                        
                except Exception as inner_e:
                    app.logger.error(f"Échec de l'approche alternative: {str(inner_e)}")
                    return jsonify({"error": f"Erreur lors du traitement du CSV: {str(e)}"}), 400
        else:
            return jsonify({"error": "Le fichier doit être au format CSV"}), 400
            
    except Exception as e:
        app.logger.error(f"Erreur lors de l'upload CSV vacataire: {str(e)}")
        return jsonify({"error": f"Erreur lors de l'import: {str(e)}"}), 500
@app.route('/api/vacataire/delete/<string:id>', methods=['DELETE'])
@token_required
def delete_vacataire(current_user, id):
    """Endpoint pour supprimer un vacataire"""
    try:
        result = vacataire_collection.delete_one({"id": id})
        
        if result.deleted_count:
            return jsonify({"message": "Vacataire supprimé avec succès"}), 200
        else:
            return jsonify({"error": "Vacataire non trouvé"}), 404
            
    except Exception as e:
        app.logger.error(f"Erreur lors de la suppression d'un vacataire: {str(e)}")
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500

@app.route('/api/vacataire/update/<string:id>', methods=['PUT'])
@token_required
def update_vacataire(current_user, id):
    """Endpoint pour mettre à jour un vacataire"""
    try:
        data = request.json
        
        # Vérifier si le vacataire existe
        existing = vacataire_collection.find_one({"id": id})
        if not existing:
            return jsonify({"error": "Vacataire non trouvé"}), 404
            
        # Ajouter les métadonnées de mise à jour
        data['date_modification'] = datetime.now().isoformat()
        data['modifie_par'] = current_user.get('username', 'system')
        
        # Mettre à jour le document
        result = vacataire_collection.update_one(
            {"id": id},
            {"$set": data}
        )
        
        if result.modified_count:
            return jsonify({"message": "Vacataire mis à jour avec succès"}), 200
        else:
            return jsonify({"message": "Aucune modification effectuée"}), 200
            
    except Exception as e:
        app.logger.error(f"Erreur lors de la mise à jour d'un vacataire: {str(e)}")
        return jsonify({"error": f"Erreur lors de la mise à jour: {str(e)}"}), 500

@app.route('/api/vacataire/stats', methods=['GET'])
@token_required
def get_vacataire_stats(current_user):
    """Endpoint pour récupérer les statistiques des vacataires"""
    try:
        # Récupérer tous les documents de la collection vacataire
        cursor = vacataire_collection.find({}, {'_id': 0})
        vacataires = list(cursor)
        
        # Statistiques par profession
        professions = {}
        pays = {}
        etats_recrutement = {}
        
        for v in vacataires:
            # Compter par profession
            profession = v.get('Type de profession', '')
            if profession:
                professions[profession] = professions.get(profession, 0) + 1
                
            # Compter par pays
            pays_val = v.get('Pays', '')
            if pays_val:
                pays[pays_val] = pays.get(pays_val, 0) + 1
                
            # Compter par état de recrutement
            etat = v.get('État recrutement', '')
            if etat:
                etats_recrutement[etat] = etats_recrutement.get(etat, 0) + 1
        
        # Préparer les données pour les heures
        vacataires_heures = []
        for v in vacataires:
            try:
                heures = float(v.get('Nombre d\'heures estimées', 0))
                if heures > 0:
                    vacataires_heures.append({
                        'nom': f"{v.get('Prénom', '')} {v.get('Nom', '')}",
                        'heures': heures
                    })
            except:
                pass
        
        # Trier et prendre les 10 premiers
        vacataires_heures.sort(key=lambda x: x['heures'], reverse=True)
        top_10_heures = vacataires_heures[:10]
        
        # Formatter les résultats
        stats = {
            "profession": {
                "labels": list(professions.keys()),
                "values": list(professions.values())
            },
            "pays": {
                "labels": list(pays.keys()),
                "values": list(pays.values())
            },
            "etat_recrutement": {
                "labels": list(etats_recrutement.keys()),
                "values": list(etats_recrutement.values())
            },
            "heures": {
                "labels": [v['nom'] for v in top_10_heures],
                "values": [v['heures'] for v in top_10_heures]
            }
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des statistiques vacataires: {str(e)}")
        return jsonify({"error": f"Erreur lors de la récupération des statistiques: {str(e)}"}), 500
##############################################cat spécial#######################
# Ajoutez cette route pour l'importation CSV des catégories spéciales
@app.route('/api/cat-special/upload', methods=['POST'])
@token_required
def upload_cat_special_file(current_user):
    """Endpoint pour uploader un fichier CSV des catégories spéciales"""
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
            # Log plus d'information sur le fichier
            print(f"Traitement du fichier: {file.filename}")
            
            # Déterminer le type de fichier selon le nom
            file_type = None
            if "vacataires" in file.filename.lower():
                file_type = "vacataires"
            elif "convention" in file.filename.lower():
                file_type = "convention"
            else:
                file_type = "autre"  # Type par défaut si non reconnu
                
            print(f"Type de fichier détecté: {file_type}")
            
            # Lecture du fichier CSV
            df = pd.read_csv(file, encoding='utf-8')
            
            print(f"Dimensions du DataFrame: {df.shape}")
            print("Colonnes dans le fichier:", df.columns.tolist())
            
            # Vérification des colonnes requises selon le type
            if file_type == "vacataires" or file_type == "convention":
                required_columns = ['Prénom', 'Nom', 'Etablissement', 'Adresse mail']
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    return jsonify({
                        "error": f"Format du fichier non reconnu. Colonnes manquantes: {', '.join(missing_columns)}"
                    }), 400
            
            # Conversion des données en dictionnaire pour MongoDB
            records = df.to_dict('records')
            
            # Ajouter des champs supplémentaires
            for record in records:
                record['created_by'] = current_user['username']
                record['created_at'] = datetime.utcnow().isoformat()
                record['file_type'] = file_type
            
            # Insertion dans MongoDB
            if records:
                result = donnees_vac_collection.insert_many(records)
                inserted_count = len(result.inserted_ids)
                print(f"Documents insérés: {inserted_count}")
                
                return jsonify({
                    "message": f"Importation réussie! {inserted_count} enregistrements insérés.",
                    "records_inserted": inserted_count,
                    "success": True
                }), 200
            else:
                return jsonify({
                    "error": "Aucun enregistrement trouvé dans le fichier CSV"
                }), 400
                
        except Exception as e:
            import traceback
            traceback_str = traceback.format_exc()
            print(f"Erreur détaillée: {traceback_str}")
            return jsonify({"error": f"Erreur lors du traitement du fichier: {str(e)}"}), 500
    
    return jsonify({"error": "Format de fichier non pris en charge. Seuls les fichiers CSV sont acceptés."}), 400

# Ajoutez cette route pour récupérer les données des catégories spéciales
@app.route('/api/cat-special', methods=['GET'])
@token_required
def get_cat_special_data(current_user):
    """Endpoint pour récupérer les données des catégories spéciales"""
    try:
        # Récupérer tous les enregistrements
        records = list(donnees_vac_collection.find({}, {'_id': {'$toString': '$_id'}}))
        
        return jsonify({
            "data": records,
            "success": True,
            "count": len(records)
        }), 200
    except Exception as e:
        return jsonify({"error": f"Erreur lors de la récupération des données: {str(e)}"}), 500
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

