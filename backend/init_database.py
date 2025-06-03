#!/usr/bin/env python3
"""
Script d'initialisation de la base de données AppISIS
Crée la base de données, les collections et un utilisateur administrateur par défaut
"""

from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime
import json

# Configuration (même que config.py)
MONGO_URI = 'mongodb://localhost:27017/'
MONGO_DB = 'AppISIS'
MONGO_COLLECTION_USERS = 'utilisateurs'
MONGO_COLLECTION_DATA = 'donnees_etudiants'
MONGO_COLLECTION_ENSEIGNEMENT = 'donnees_enseignement'

def init_database():
    """Initialise la base de données AppISIS"""
    try:
        # Connexion à MongoDB
        client = MongoClient(MONGO_URI)
        print("✓ Connexion à MongoDB réussie")
        
        # Sélection de la base de données
        db = client[MONGO_DB]
        print(f"✓ Base de données '{MONGO_DB}' sélectionnée")
        
        # Collections
        users_collection = db[MONGO_COLLECTION_USERS]
        data_collection = db[MONGO_COLLECTION_DATA]
        enseignement_collection = db[MONGO_COLLECTION_ENSEIGNEMENT]
        
        # Création des index pour optimiser les requêtes
        print("Création des index...")
        
        # Index pour la collection utilisateurs
        users_collection.create_index("username", unique=True)
        users_collection.create_index("email", unique=True)
        print("✓ Index utilisateurs créés")
        
        # Index pour la collection données
        data_collection.create_index("annee")
        data_collection.create_index("uploaded_by")
        data_collection.create_index("uploaded_at")
        print("✓ Index données créés")
        
        # Index pour la collection enseignement
        enseignement_collection.create_index([("annee", 1), ("semestre", 1)], unique=True)
        enseignement_collection.create_index("uploaded_by")
        enseignement_collection.create_index("uploaded_at")
        print("✓ Index enseignement créés")
        
        # Vérification si un administrateur existe déjà
        admin_exists = users_collection.find_one({"role": "admin"})
        
        if not admin_exists:
            # Création de l'utilisateur administrateur par défaut
            admin_user = {
                'username': 'admin',
                'password': generate_password_hash('admin123'),  # À changer en production !
                'email': 'admin@isis-school.fr',
                'role': 'admin',
                'created_at': datetime.utcnow(),
                'is_active': True,
                'last_login': None,
                'first_name': 'Administrateur',
                'last_name': 'Système'
            }
            
            result = users_collection.insert_one(admin_user)
            print(f"✓ Utilisateur administrateur créé avec l'ID: {result.inserted_id}")
            print("  Username: admin")
            print("  Password: admin123")
            print("  ⚠️  ATTENTION: Changez ce mot de passe en production !")
        else:
            print("✓ Un administrateur existe déjà")
        
        # Création d'utilisateurs de test (optionnel)
        create_test_users = input("\nVoulez-vous créer des utilisateurs de test ? (y/n): ").lower() == 'y'
        
        if create_test_users:
            test_users = [
                {
                    'username': 'responsable_recherche',
                    'password': generate_password_hash('test123'),
                    'email': 'recherche@isis-school.fr',
                    'role': 'responsable_recherche',
                    'created_at': datetime.utcnow(),
                    'is_active': True,
                    'last_login': None,
                    'first_name': 'Responsable',
                    'last_name': 'Recherche'
                },
                {
                    'username': 'responsable_admin',
                    'password': generate_password_hash('test123'),
                    'email': 'radmin@isis-school.fr',
                    'role': 'responsable_admin',
                    'created_at': datetime.utcnow(),
                    'is_active': True,
                    'last_login': None,
                    'first_name': 'Responsable',
                    'last_name': 'Administratif'
                },
                {
                    'username': 'secretaire',
                    'password': generate_password_hash('test123'),
                    'email': 'secretaire@isis-school.fr',
                    'role': 'secretaire',
                    'created_at': datetime.utcnow(),
                    'is_active': True,
                    'last_login': None,
                    'first_name': 'Secrétaire',
                    'last_name': 'École'
                }
            ]
            
            for user in test_users:
                # Vérifier si l'utilisateur existe déjà
                if not users_collection.find_one({"username": user['username']}):
                    result = users_collection.insert_one(user)
                    print(f"✓ Utilisateur de test '{user['username']}' créé")
                else:
                    print(f"✓ Utilisateur '{user['username']}' existe déjà")
        
        # Insertion de données de test (optionnel)
        create_test_data = input("\nVoulez-vous insérer des données de test ? (y/n): ").lower() == 'y'
        
        if create_test_data:
            # Données effectifs étudiants
            test_data = [
                {
                    'annee': 2021,
                    'nombre_fie1': 120,
                    'nombre_fie2': 95,
                    'nombre_fie3': 88,
                    'taux_boursiers': 0.25,
                    'nombre_diplomes': 82,
                    'nombre_handicapes': 8,
                    'nombre_etrangers': 15,
                    'nombre_demissionnes': 5,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                },
                {
                    'annee': 2022,
                    'nombre_fie1': 133,
                    'nombre_fie2': 102,
                    'nombre_fie3': 94,
                    'taux_boursiers': 0.28,
                    'nombre_diplomes': 89,
                    'nombre_handicapes': 11,
                    'nombre_etrangers': 18,
                    'nombre_demissionnes': 7,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                },
                {
                    'annee': 2023,
                    'nombre_fie1': 139,
                    'nombre_fie2': 108,
                    'nombre_fie3': 96,
                    'taux_boursiers': 0.32,
                    'nombre_diplomes': 91,
                    'nombre_handicapes': 12,
                    'nombre_etrangers': 22,
                    'nombre_demissionnes': 6,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                }
            ]
            
            # Supprimer les anciennes données de test
            data_collection.delete_many({"uploaded_by": "admin"})
            
            # Insérer les nouvelles données
            result = data_collection.insert_many(test_data)
            print(f"✓ {len(result.inserted_ids)} enregistrements de données étudiants de test insérés")
            
            # Données enseignement
            test_enseignement_data = [
                {
                    'annee': 2023,
                    'semestre': 'S5',
                    'nombre_cours': 8,
                    'nombre_ue': 4,
                    'heures_cm': 120,
                    'heures_td': 80,
                    'heures_tp': 60,
                    'heures_projet': 40,
                    'satisfaction': 85.5,
                    'nombre_evaluations': 12,
                    'nombre_projets': 4,
                    'taux_reussite': 78.2,
                    'innovations_pedagogiques': 2,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                },
                {
                    'annee': 2023,
                    'semestre': 'S6',
                    'nombre_cours': 7,
                    'nombre_ue': 4,
                    'heures_cm': 100,
                    'heures_td': 90,
                    'heures_tp': 70,
                    'heures_projet': 50,
                    'satisfaction': 82.7,
                    'nombre_evaluations': 10,
                    'nombre_projets': 5,
                    'taux_reussite': 80.5,
                    'innovations_pedagogiques': 1,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                },
                {
                    'annee': 2024,
                    'semestre': 'S5',
                    'nombre_cours': 9,
                    'nombre_ue': 5,
                    'heures_cm': 125,
                    'heures_td': 85,
                    'heures_tp': 65,
                    'heures_projet': 45,
                    'satisfaction': 87.2,
                    'nombre_evaluations': 14,
                    'nombre_projets': 6,
                    'taux_reussite': 81.3,
                    'innovations_pedagogiques': 3,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                },
                {
                    'annee': 2024,
                    'semestre': 'S6',
                    'nombre_cours': 8,
                    'nombre_ue': 5,
                    'heures_cm': 110,
                    'heures_td': 95,
                    'heures_tp': 75,
                    'heures_projet': 55,
                    'satisfaction': 84.8,
                    'nombre_evaluations': 12,
                    'nombre_projets': 7,
                    'taux_reussite': 82.9,
                    'innovations_pedagogiques': 2,
                    'uploaded_by': 'admin',
                    'uploaded_at': datetime.utcnow()
                }
            ]
            
            # Supprimer les anciennes données de test d'enseignement
            enseignement_collection.delete_many({"uploaded_by": "admin"})
            
            # Insérer les nouvelles données d'enseignement
            result_enseignement = enseignement_collection.insert_many(test_enseignement_data)
            print(f"✓ {len(result_enseignement.inserted_ids)} enregistrements de données d'enseignement de test insérés")
        
        # Affichage du résumé
        print("\n" + "="*50)
        print("RÉSUMÉ DE L'INITIALISATION")
        print("="*50)
        print(f"Base de données: {MONGO_DB}")
        print(f"Collections créées:")
        print(f"  - {MONGO_COLLECTION_USERS}")
        print(f"  - {MONGO_COLLECTION_DATA}")
        print(f"  - {MONGO_COLLECTION_ENSEIGNEMENT}")
        
        # Statistiques
        users_count = users_collection.count_documents({})
        data_count = data_collection.count_documents({})
        enseignement_count = enseignement_collection.count_documents({})
        
        print(f"\nStatistiques:")
        print(f"  - Utilisateurs: {users_count}")
        print(f"  - Enregistrements de données étudiants: {data_count}")
        print(f"  - Enregistrements de données d'enseignement: {enseignement_count}")
        
        print(f"\nCollections disponibles dans {MONGO_DB}:")
        for collection_name in db.list_collection_names():
            print(f"  - {collection_name}")
        
        print("\n✓ Initialisation terminée avec succès !")
        
        client.close()
        
    except Exception as e:
        print(f" Erreur lors de l'initialisation: {e}")
        return False
    
    return True

def reset_database():
    """Remet à zéro la base de données (ATTENTION: supprime toutes les données)"""
    confirm = input("  ATTENTION: Cette action va supprimer toutes les données de la base AppISIS.\nÊtes-vous sûr ? Tapez 'RESET' pour confirmer: ")
    
    if confirm != 'RESET':
        print("Opération annulée.")
        return
    
    try:
        client = MongoClient(MONGO_URI)
        client.drop_database(MONGO_DB)
        print(f"✓ Base de données '{MONGO_DB}' supprimée")
        client.close()
        
        # Réinitialiser
        print("Réinitialisation...")
        init_database()
        
    except Exception as e:
        print(f" Erreur lors de la remise à zéro: {e}")
        

def show_database_info():
    """Affiche des informations sur la base de données"""
    try:
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB]
        
        print(f"\n INFORMATIONS SUR LA BASE {MONGO_DB}")
        print("="*50)
        
        # Collections
        collections = db.list_collection_names()
        print(f"Collections: {len(collections)}")
        for coll in collections:
            count = db[coll].count_documents({})
            print(f"  - {coll}: {count} documents")
        
        # Utilisateurs par rôle
        if MONGO_COLLECTION_USERS in collections:
            print(f"\n👥 Utilisateurs par rôle:")
            pipeline = [
                {"$group": {"_id": "$role", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            for result in db[MONGO_COLLECTION_USERS].aggregate(pipeline):
                print(f"  - {result['_id']}: {result['count']}")
        
        # Données par année
        if MONGO_COLLECTION_DATA in collections:
            print(f"\n Données étudiants par année:")
            pipeline = [
                {"$group": {"_id": "$annee", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}}
            ]
            for result in db[MONGO_COLLECTION_DATA].aggregate(pipeline):
                print(f"  - {result['_id']}: {result['count']} enregistrement(s)")
        
        # Données d'enseignement par année/semestre
        if MONGO_COLLECTION_ENSEIGNEMENT in collections:
            print(f"\n Données d'enseignement par année/semestre:")
            pipeline = [
                {"$group": {"_id": {"annee": "$annee", "semestre": "$semestre"}, "count": {"$sum": 1}}},
                {"$sort": {"_id.annee": 1, "_id.semestre": 1}}
            ]
            for result in db[MONGO_COLLECTION_ENSEIGNEMENT].aggregate(pipeline):
                print(f"  - {result['_id']['annee']}/{result['_id']['semestre']}: {result['count']} enregistrement(s)")
        
        client.close()
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des informations: {e}")

if __name__ == "__main__":
    print(" SCRIPT D'INITIALISATION DE LA BASE AppISIS")
    print("="*50)
    
    while True:
        print("\nOptions disponibles:")
        print("1. Initialiser la base de données")
        print("2. Afficher les informations de la base")
        print("3. Remettre à zéro la base (DANGER)")
        print("4. Quitter")
        
        choice = input("\nVotre choix (1-4): ").strip()
        
        if choice == '1':
            init_database()
        elif choice == '2':
            show_database_info()
        elif choice == '3':
            reset_database()
        elif choice == '4':
            print("Au revoir !")
            break
        else:
            print("Choix invalide. Veuillez choisir entre 1 et 4.")