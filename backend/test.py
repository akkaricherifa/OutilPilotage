# from pymongo import MongoClient

# try:
#     client = MongoClient('mongodb://localhost:27017/')
#     print("Connexion réussie!")
    
#     db = client['statistiques_etudiants']  
#     collection = db['donnees_etudiants']
    
#     # Insertion d'un document factice pour créer la collection
#     collection.insert_one({"test": "création"})
#     print("Base et collection créées avec succès!")
    
#     # Vérification
#     print("Bases disponibles:", client.list_database_names())
#     print("Collections dans la base:", db.list_collection_names())
    
#     # Nettoyage (optionnel)
#     collection.delete_one({"test": "création"})
#     client.close()
    
# except Exception as e:
#     print("Échec:", e)