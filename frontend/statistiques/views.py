# statistiques/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.views.decorators.csrf import csrf_exempt
from .forms import CSVUploadForm, UserRegisterForm, DataUpdateForm
from .models import CSVFile, UserRole
import requests
import json
import logging
import math
from django.core.cache import cache
import json
import pandas as pd
import numpy as np
import tempfile
import os
FLASK_API_URL = 'http://localhost:5000'
logger = logging.getLogger(__name__)

def clean_json_data(data):
    """Nettoie les données JSON pour supprimer les valeurs NaN, Infinity, -Infinity"""
    
    if isinstance(data, dict):
        return {k: clean_json_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_json_data(item) for item in data]
    elif isinstance(data, float):
        # Remplacer NaN et Infinity par None (null en JSON)
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    else:
        return data
def home(request):
    """Page d'accueil"""
    return render(request, 'statistiques/home.html')

def register(request):
    """Vue pour l'inscription des utilisateurs - Version simplifiée"""
    if request.method == 'POST':
        # Récupérer les données du formulaire
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        role = request.POST.get('role')
        
        # Validation basique
        if not all([username, email, password1, password2, role]):
            messages.error(request, "Tous les champs sont requis.")
            return render(request, 'statistiques/register.html')
        
        if password1 != password2:
            messages.error(request, "Les mots de passe ne correspondent pas.")
            return render(request, 'statistiques/register.html')
        
        if len(password1) < 8:
            messages.error(request, "Le mot de passe doit contenir au moins 8 caractères.")
            return render(request, 'statistiques/register.html')
        
        try:
            # Créer l'utilisateur dans l'API Flask
            api_data = {
                'username': username,
                'email': email,
                'password': password1,
                'role': role
            }
            
            response = requests.post(f"{settings.API_URL}/register", json=api_data, timeout=10)
            
            if response.status_code == 201:
                messages.success(request, 'Compte créé avec succès! Votre compte est en attente d\'approbation par un administrateur.')
                return redirect('login')
            else:
                api_response = response.json()
                messages.error(request, f"Erreur: {api_response.get('error', 'Erreur inconnue')}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur de connexion à l'API: {e}")
            messages.error(request, "Erreur de connexion au serveur. Veuillez réessayer.")
        except Exception as e:
            logger.error(f"Erreur lors de l'inscription: {e}")
            messages.error(request, "Une erreur s'est produite lors de l'inscription.")
    
    return render(request, 'statistiques/register.html')

def login_view(request):
    """Vue pour la connexion"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if username and password:
            try:
                # Authentification via l'API Flask
                api_data = {'username': username, 'password': password}
                response = requests.post(f"{settings.API_URL}/login", json=api_data, timeout=10)
                
                if response.status_code == 200:
                    api_response = response.json()
                    
                    # Stocker le token dans la session
                    request.session['api_token'] = api_response['token']
                    request.session['user_info'] = api_response['user']
                    
                    # Authentification Django (optionnelle, pour compatibilité)
                    user = authenticate(request, username=username, password=password)
                    if user:
                        auth_login(request, user)
                    
                    messages.success(request, f"Bienvenue {api_response['user']['username']} !")
                    return redirect('dashboard')
                elif response.status_code == 403:
                    api_response = response.json()
                    error_message = api_response.get('error', 'Accès refusé')
                    if "en attente d'approbation" in error_message:
                        messages.warning(request, "Votre compte est en attente d'approbation par un administrateur.")
                    else:
                        messages.error(request, error_message)
                else:
                    api_response = response.json()
                    messages.error(request, api_response.get('error', 'Identifiants incorrects'))
                
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur de connexion à l'API: {e}")
                messages.error(request, "Erreur de connexion au serveur. Veuillez réessayer.")
            except Exception as e:
                logger.error(f"Erreur lors de la connexion: {e}")
                messages.error(request, "Une erreur s'est produite lors de la connexion.")
        else:
            messages.error(request, "Veuillez remplir tous les champs.")
    
    return render(request, 'statistiques/login.html')

def logout_view(request):
    """Vue pour la déconnexion"""
    try:
        # Déconnexion de l'API si token disponible
        token = request.session.get('api_token')
        if token:
            headers = {'Authorization': f'Bearer {token}'}
            requests.post(f"{settings.API_URL}/logout", headers=headers, timeout=5)
        
        # Nettoyer la session
        request.session.flush()
        
        # Déconnexion Django
        auth_logout(request)
        
        messages.info(request, "Vous avez été déconnecté avec succès.")
    except Exception as e:
        logger.error(f"Erreur lors de la déconnexion: {e}")
    
    return redirect('home')

def is_api_authenticated(request):
    """Vérifie si l'utilisateur est authentifié via l'API"""
    token = request.session.get('api_token')
    if not token:
        return False, None
    
    try:
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(f"{settings.API_URL}/check-auth", headers=headers, timeout=5)
        if response.status_code == 200:
            return True, response.json()['user']
        else:
            # Token invalide, nettoyer la session
            request.session.pop('api_token', None)
            request.session.pop('user_info', None)
            return False, None
    except:
        return False, None

def api_authenticated_required(view_func):
    """Décorateur pour vérifier l'authentification API"""
    def wrapper(request, *args, **kwargs):
        is_auth, user_info = is_api_authenticated(request)
        if not is_auth:
            messages.error(request, "Vous devez être connecté pour accéder à cette page.")
            return redirect('login')
        request.api_user = user_info
        return view_func(request, *args, **kwargs)
    return wrapper

@api_authenticated_required
def dashboard(request):
    """Vue pour le tableau de bord principal"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(f"{settings.API_URL}/statistics", headers=headers, timeout=10)
        if response.status_code == 200:
            statistics = response.json()
        else:
            statistics = None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API dashboard: {e}")
        statistics = None
    
    return render(request, 'statistiques/dashboard.html', {
        'statistics': statistics,
        'user_info': request.session.get('user_info', {})
    })

@api_authenticated_required
def upload_csv(request):
    """Vue pour télécharger un fichier CSV - CORRIGÉE"""
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Pas besoin de sauvegarder en Django, envoyer directement à l'API
            token = request.session.get('api_token')
            headers = {'Authorization': f'Bearer {token}'}
            
            try:
                # Préparer le fichier pour l'envoi
                uploaded_file = request.FILES['file']
                files = {
                    'file': (uploaded_file.name, uploaded_file.read(), 'text/csv')
                }
                
                # Envoyer à l'API Flask
                response = requests.post(
                    f"{settings.API_URL}/upload", 
                    files=files, 
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 200:
                    api_response = response.json()
                    success_message = f"Fichier CSV traité avec succès! {api_response.get('records_inserted', 0)} nouveaux enregistrements, {api_response.get('records_updated', 0)} mis à jour."
                    
                    # Gestion des requêtes AJAX
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': True, 'message': success_message})
                    
                    messages.success(request, success_message)
                    
                    # Redirection selon le contexte
                    if 'effectifs' in request.path or request.GET.get('source') == 'effectifs':
                        return redirect('effectifs_etudiants')
                    return redirect('dashboard')
                    
                else:
                    api_response = response.json()
                    error_message = f"Erreur API: {api_response.get('error', 'Erreur inconnue')}"
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': error_message}, status=response.status_code)
                    
                    messages.error(request, error_message)
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur upload API: {e}")
                error_message = "Erreur de connexion lors de l'upload du fichier."
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': error_message}, status=500)
                
                messages.error(request, error_message)
            
        else:
            # Gestion des erreurs de formulaire
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {field: str(errors) for field, errors in form.errors.items()}
                return JsonResponse({'success': False, 'errors': errors}, status=400)
            
            messages.error(request, "Formulaire invalide. Veuillez vérifier les données saisies.")
    else:
        form = CSVUploadForm()
    
    return render(request, 'statistiques/upload_csv.html', {'form': form})


@api_authenticated_required
def view_data(request):
    """Vue pour afficher les données"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(f"{settings.API_URL}/data", headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
        else:
            data = []
            api_response = response.json()
            messages.warning(request, f"Erreur API: {api_response.get('error', 'Impossible de récupérer les données')}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API view_data: {e}")
        data = []
        messages.error(request, "Erreur de connexion pour récupérer les données.")
    
    return render(request, 'statistiques/view_data.html', {'data': data})


@api_authenticated_required
def update_data(request):
    """Vue pour mettre à jour les données - CORRIGÉE"""
    if request.method == 'POST':
        form = DataUpdateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            token = request.session.get('api_token')
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            
            try:
                response = requests.post(
                    f"{settings.API_URL}/update",
                    json=data,
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    api_response = response.json()
                    success_message = api_response.get('message', 'Données mises à jour avec succès!')
                    
                    # Gestion des requêtes AJAX
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': True, 'message': success_message})
                    
                    messages.success(request, success_message)
                    
                    # Redirection selon le contexte
                    if 'effectifs' in request.path or request.GET.get('source') == 'effectifs':
                        return redirect('effectifs_etudiants')
                    return redirect('view_data')
                    
                else:
                    api_response = response.json()
                    error_message = f"Erreur API: {api_response.get('error', 'Erreur lors de la mise à jour')}"
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'message': error_message}, status=400)
                    
                    messages.error(request, error_message)
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur API update: {e}")
                error_message = "Erreur de connexion lors de la mise à jour."
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'message': error_message}, status=500)
                
                messages.error(request, error_message)
            
        else:
            # Gestion des erreurs de formulaire
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {field: str(errors) for field, errors in form.errors.items()}
                return JsonResponse({'success': False, 'errors': errors}, status=400)
            
            messages.error(request, "Formulaire invalide. Veuillez vérifier les données saisies.")
    else:
        form = DataUpdateForm()
    
    return render(request, 'statistiques/update_data.html', {'form': form})

# Vue AJAX pour vérifier le statut de l'API
@csrf_exempt
def api_status(request):
    """Vérifie le statut de l'API Flask"""
    try:
        response = requests.get(f"{settings.API_BASE_URL}/", timeout=5)
        if response.status_code == 200:
            return JsonResponse({'status': 'online', 'message': 'API accessible'})
        else:
            return JsonResponse({'status': 'error', 'message': f'API répond avec le code {response.status_code}'})
    except requests.exceptions.RequestException as e:
        return JsonResponse({'status': 'offline', 'message': f'API inaccessible: {str(e)}'})

# Vue pour les administrateurs uniquement
@api_authenticated_required
def admin_users(request):
    """Vue pour gérer les utilisateurs (admin seulement)"""
    user_info = request.session.get('user_info', {})
    if user_info.get('role') != 'admin':
        messages.error(request, "Accès interdit. Seuls les administrateurs peuvent accéder à cette page.")
        return redirect('dashboard')
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(f"{settings.API_URL}/users", headers=headers, timeout=10)
        if response.status_code == 200:
            users_data = response.json()
            
            # Ajouter un ID spécial à chaque utilisateur
            for i, user in enumerate(users_data, 1):
                # Préférer l'ID existant s'il est présent, sinon créer un ID user-X
                if not user.get('id'):
                    user['id'] = f"user-{i}"
                
                # S'assurer que approval_status est défini
                if 'approval_status' not in user:
                    user['approval_status'] = 'approved' if user.get('is_active', False) else 'pending'
                
                # Formater les dates pour l'affichage si elles existent
                if 'created_at' in user and user['created_at']:
                    try:
                        user['created_at'] = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00'))
                    except:
                        pass
                
                if 'last_login' in user and user['last_login']:
                    try:
                        user['last_login'] = datetime.fromisoformat(user['last_login'].replace('Z', '+00:00'))
                    except:
                        pass
                
                # Log pour débogage
                logger.info(f"Utilisateur {i}: id={user.get('id')}, approval_status={user.get('approval_status')}")
        else:
            users_data = []
            api_response = response.json()
            messages.error(request, f"Erreur API: {api_response.get('error', 'Impossible de récupérer les utilisateurs')}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API admin_users: {e}")
        users_data = []
        messages.error(request, "Erreur de connexion pour récupérer les utilisateurs.")
    
    return render(request, 'statistiques/admin_users.html', {
        'users_data': users_data,
        'api_url': settings.API_URL
    })

@api_authenticated_required
def approve_user_proxy(request, user_id):
    """Proxy pour approuver/rejeter un utilisateur via l'API Flask"""
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
    
    token = request.session.get('api_token')
    if not token:
        return JsonResponse({"error": "Non authentifié"}, status=401)
    
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        # Analyser le corps de la requête JSON
        import json
        data = json.loads(request.body)
        status = data.get('status')
        username = data.get('username', '')  # Récupérer le nom d'utilisateur si fourni
        
        if not status or status not in ['approved', 'rejected']:
            return JsonResponse({"error": "Statut invalide"}, status=400)
        
        # Log pour débogage
        logger.info(f"Proxy approve_user: Tentative d'approbation de l'utilisateur {user_id} ({username}) avec statut {status}")
        
        # Construire la requête API
        api_url = f"{settings.API_URL}/users/approve/{user_id}"
        logger.info(f"URL API appelée: {api_url}")
        
        # Envoyer la requête avec toutes les données disponibles
        response = requests.post(
            api_url,
            headers=headers,
            json=data,  # Envoyer toutes les données, y compris username si disponible
            timeout=15  # Augmenter le timeout
        )
        
        # Log de débogage
        logger.info(f"Proxy approve_user: Status={response.status_code}")
        logger.info(f"Réponse: {response.text[:1000]}")  # Limiter la taille du log
        
        # Si la réponse est réussie
        if response.status_code in [200, 201, 204]:
            try:
                json_response = response.json()
                logger.info(f"Approbation réussie pour l'utilisateur {user_id} ({username})")
                return JsonResponse(json_response, status=response.status_code)
            except json.JSONDecodeError:
                logger.warning(f"Réponse non-JSON reçue avec statut {response.status_code}")
                return HttpResponse(response.text, status=response.status_code, content_type='text/plain')
        else:
            try:
                json_response = response.json()
                logger.error(f"Erreur API: {json_response}")
                return JsonResponse(json_response, status=response.status_code)
            except json.JSONDecodeError:
                logger.error(f"Erreur API (texte brut): {response.text}")
                return HttpResponse(response.text, status=response.status_code, content_type='text/plain')
        
    except json.JSONDecodeError:
        logger.error("Format JSON invalide dans la requête")
        return JsonResponse({"error": "Format JSON invalide"}, status=400)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur proxy approve_user: {e}")
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.error(f"Erreur inattendue dans approve_user_proxy: {e}")
        return JsonResponse({"error": str(e)}, status=500)
##################################################################################################cat etudiants ###########################################################################
@api_authenticated_required
def effectifs_etudiants(request):
    """Vue pour afficher les étudiants existants"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    etudiants = []
    annees = []
    niveaux = []
    
    try:
        # Corriger l'URL pour récupérer tous les étudiants
        api_url = f"{settings.API_BASE_URL}/api/etudiants"
        logger.info(f"Appel à l'API: {api_url}")
        
        response = requests.get(api_url, headers=headers, timeout=30)  # Augmenter le timeout
        logger.info(f"Réponse de l'API: Status {response.status_code}")
        
        if response.status_code == 200:
            # Récupérer la liste des étudiants
            etudiants = response.json()
            logger.info(f"Données étudiants récupérées: {len(etudiants)} étudiants")
            
            # Récupérer les années disponibles
            annees_response = requests.get(f"{settings.API_BASE_URL}/api/etudiants/annees", headers=headers, timeout=15)
            if annees_response.status_code == 200:
                annees = annees_response.json().get('annees', [])
                logger.info(f"Années récupérées: {annees}")
            else:
                logger.warning("Impossible de récupérer les années, extraction depuis les données étudiants")
                # Extraire les années à partir des données étudiants
                annees = sorted(list(set([etudiant.get('annee', '') for etudiant in etudiants if etudiant.get('annee')])))
                
            # Récupérer les niveaux disponibles
            niveaux_response = requests.get(f"{settings.API_BASE_URL}/api/etudiants/niveaux", headers=headers, timeout=15)
            if niveaux_response.status_code == 200:
                niveaux = niveaux_response.json().get('niveaux', [])
                logger.info(f"Niveaux récupérés: {niveaux}")
            else:
                logger.warning("Impossible de récupérer les niveaux, extraction depuis les données étudiants")
                # Extraire les niveaux à partir des données étudiants
                niveaux = sorted(list(set([etudiant.get('niveau', '') for etudiant in etudiants if etudiant.get('niveau')])))
        else:
            logger.error(f"Erreur API étudiants: {response.status_code} - {response.text}")
            messages.error(request, "Erreur lors de la récupération des données étudiants.")
            
    except Exception as e:
        logger.error(f"Erreur: {str(e)}")
        messages.error(request, f"Une erreur s'est produite: {str(e)}")
    
    # Si aucune donnée n'est disponible
    if not etudiants:
        messages.info(request, "Aucun étudiant trouvé dans la base de données.")
    
    # Convertir les données en JSON pour le JavaScript
    import json
    etudiants_json = json.dumps(etudiants)
    
    return render(request, 'statistiques/effectifs_etudiants.html', {
        'etudiants': etudiants_json,
        'annees': annees,
        'niveaux': niveaux,  # Passer les niveaux au template
        'api_url': settings.API_BASE_URL
    })

@api_authenticated_required
def upload_csv_etudiants(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
    
    if 'file' not in request.FILES:
        return JsonResponse({"error": "Aucun fichier n'a été envoyé"}, status=400)
    
    file = request.FILES['file']
    
    if not file.name.endswith('.csv'):
        return JsonResponse({"error": "Seuls les fichiers CSV sont acceptés"}, status=400)
    
    try:
        # Lire le contenu du fichier CSV
        file_content = file.read().decode('utf-8', errors='replace')
        
        # Diviser le contenu en lignes
        lines = file_content.strip().split('\n')
        
        # La première ligne contient les en-têtes
        headers = [h.strip() for h in lines[0].split(',')]
        
        # Traiter chaque ligne pour créer les documents étudiants
        etudiants = []
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if not line:  # Ignorer les lignes vides
                continue
                
            # Diviser la ligne en colonnes
            columns = [col.strip() for col in line.split(',')]
            
            # Créer le document étudiant avec tous les champs du CSV
            etudiant = {}
            for j, col in enumerate(columns):
                if j < len(headers):
                    etudiant[headers[j]] = col
            
            etudiants.append(etudiant)
        
        # Envoyer les données à l'API
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        
        response = requests.post(
            f"{settings.API_URL}/etudiants/upload-data",
            json={'etudiants': etudiants},
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({
                "success": True,
                "message": f"Données d'étudiants importées avec succès! {len(etudiants)} étudiants traités.",
                "records_inserted": api_response.get('records_inserted', 0)
            })
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur inconnue')}, status=response.status_code)
            
    except Exception as e:
        logger.error(f"Erreur: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)
    
######################################## CATEGORIE ENSEIGNEMENT ##############################################
@api_authenticated_required
def heures_enseignement(request):
    """Vue pour la page des heures d'enseignement"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Essayer de récupérer des statistiques de base pour s'assurer que l'API est accessible
        response = requests.get(f"{settings.API_URL}/heures-enseignement/stats", headers=headers, timeout=10)
        if response.status_code != 200:
            messages.warning(request, f"Impossible de récupérer les statistiques (Code: {response.status_code})")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API heures_enseignement: {e}")
        messages.error(request, "Erreur de connexion à l'API pour récupérer les statistiques.")
    
    return render(request, 'statistiques/heures_enseignement.html', {
        'user_info': request.session.get('user_info', {}),
        'settings': settings  # Passer les paramètres de configuration au template
    })

@api_authenticated_required
def enseignement(request):
    """Vue principale pour l'enseignement et la pédagogie"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les statistiques depuis l'API
        api_url = f"{settings.API_URL}/enseignement/stats"
        logger.info(f"Appel à l'API: {api_url}")
        
        response = requests.get(api_url, headers=headers, timeout=10)
        logger.info(f"Réponse de l'API: Status {response.status_code}")
        
        if response.status_code == 200:
            stats = response.json()
            logger.info(f"Données reçues: {stats.keys()}")
            
            # Vérifier la structure des données
            if 'donnees_par_semestre' in stats:
                logger.info(f"Nombre d'enregistrements: {len(stats['donnees_par_semestre'])}")
                
                # Ajouter un élément caché dans le contexte pour stocker les données brutes
                stats['donnees_brutes'] = json.dumps(stats['donnees_par_semestre'])
            else:
                logger.error("Clé 'donnees_par_semestre' manquante dans les données")
                messages.warning(request, "Structure de données incorrecte")
        else:
            stats = None
            try:
                error_msg = response.json().get('error', 'Erreur inconnue')
                logger.error(f"Erreur API: {error_msg}")
                messages.warning(request, f"Impossible de récupérer les statistiques: {error_msg}")
            except:
                logger.error(f"Erreur API non-JSON: {response.text}")
                messages.warning(request, f"Impossible de récupérer les statistiques (Code: {response.status_code})")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API enseignement: {e}")
        stats = None
        messages.error(request, "Erreur de connexion à l'API pour récupérer les statistiques d'enseignement.")
    
    return render(request, 'statistiques/enseignement.html', {
        'stats': stats,
        'user_info': request.session.get('user_info', {})
    })


@api_authenticated_required
def enseignement_add_data(request):
    """Vue pour ajouter ou mettre à jour des données d'enseignement"""
    if request.method != 'POST':
        return redirect('enseignement')
        
    try:
        # Récupérer les données du formulaire avec validation
        data = {
                'annee': int(request.POST.get('annee', 0)),
                'semestre': request.POST.get('semestre', ''),
                'nombre_cours': int(request.POST.get('nombre_cours', 0)),
                'nombre_ue': int(request.POST.get('nombre_ue', 0)),
                'heures_cm': int(request.POST.get('heures_cm', 0)),
                'heures_td': int(request.POST.get('heures_td', 0)),
                'heures_tp': int(request.POST.get('heures_tp', 0)),
                'heures_projet': int(request.POST.get('heures_projet', 0)),
                'satisfaction': float(request.POST.get('satisfaction', 0)),
                'nombre_evaluations': int(request.POST.get('nombre_evaluations') or 0),
                'nombre_projets': int(request.POST.get('nombre_projets') or 0),
                'taux_reussite': float(request.POST.get('taux_reussite') or 0),
                'innovations_pedagogiques': int(request.POST.get('innovations_pedagogiques') or 0)
            }
        # Plus de logs
        logger.info(f"Données après conversion: {data}")
        # Validation des données obligatoires
        if not data['annee'] or not data['semestre']:
            return JsonResponse({"error": "L'année et le semestre sont obligatoires."}, status=400)
        
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        
        # Log pour débogage
        logger.info(f"Envoi des données à l'API: {data}")
        
        response = requests.post(
            f"{settings.API_URL}/enseignement/update",
            json=data,
            headers=headers,
            timeout=10
        )
        
        logger.info(f"Réponse de l'API: {response.status_code} - {response.text}")
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({"message": api_response.get('message', 'Données enregistrées avec succès!')})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur lors de la mise à jour')}, status=response.status_code)
            
    except ValueError as e:
        logger.error(f"Erreur de conversion de données: {e}")
        return JsonResponse({"error": f"Erreur de validation des données: {str(e)}"}, status=400)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API enseignement_add_data: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de la mise à jour des données."}, status=500)
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        return JsonResponse({"error": f"Une erreur inattendue s'est produite: {str(e)}"}, status=500)

@api_authenticated_required
def enseignement_upload_csv(request):
    """Vue pour télécharger un fichier CSV d'enseignement"""
    if request.method != 'POST':
        return redirect('enseignement')
        
    form = CSVUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({"error": "Formulaire invalide"}, status=400)
        
    csv_file = form.save(commit=False)
    csv_file.uploaded_by = request.user
    csv_file.save()
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Envoyer le fichier à l'API Flask
        files = {
            'file': (
                csv_file.file.name,
                csv_file.file.open('rb'),
                'text/csv'
            )
        }
        response = requests.post(
            f"{settings.API_URL}/enseignement/upload", 
            files=files, 
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({"message": f"Fichier CSV traité avec succès! {api_response.get('records_inserted', 0)} enregistrements ajoutés."})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur inconnue')}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur upload API enseignement: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de l'upload du fichier."}, status=500)
    finally:
        csv_file.file.close()

@api_authenticated_required
def enseignement_delete_data(request, annee, semestre):
    """Vue pour supprimer des données d'enseignement"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.delete(
            f"{settings.API_URL}/enseignement/delete/{annee}/{semestre}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return JsonResponse({"message": "Données supprimées avec succès!"})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur lors de la suppression')}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API enseignement_delete_data: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de la suppression des données."}, status=500)
    
@api_authenticated_required
def categories_enseignement(request):
    """Vue pour les catégories d'enseignement"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les statistiques spécifiques des catégories d'enseignement
        response = requests.get(f"{settings.API_URL}/enseignement/categories/stats", headers=headers, timeout=10)
        
        if response.status_code == 200:
            stats_data = response.json()
            
            # Extraire les données nécessaires pour le template
            categories_stats = stats_data.get("categories", {})
            
            # Statistiques rapides pour l'en-tête
            quick_stats = {
                "heures_totales": stats_data.get("total_heures_enseignement", 1254),
                "satisfaction": round(stats_data.get("taux_satisfaction", 86), 1),
                "intervenants": stats_data.get("total_intervenants", 42),
                "innovations": stats_data.get("total_innovations", 18)
            }
            
        else:
            # En cas d'erreur, on utilise des données par défaut pour le prototype
            categories_stats = {
                "heures": {
                    "total": 845,
                    "evolution": 5.2,
                    "trend": "up"
                },
                "rse": {
                    "total": 124,
                    "evolution": 12.8,
                    "trend": "up"
                },
                "arion": {
                    "total": 178,
                    "evolution": 7.3,
                    "trend": "up"
                },
                "vacataires": {
                    "total": 42,
                    "evolution": 3.1,
                    "trend": "up"
                },
                "autres": {
                    "total": 107,
                    "evolution": -2.4,
                    "trend": "down"
                }
            }
            
            quick_stats = {
                "heures_totales": 1254,
                "satisfaction": 86.0,
                "intervenants": 42,
                "innovations": 18
            }
            
            api_response = response.json()
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API categories_enseignement: {e}")
        
        # Données par défaut en cas d'erreur de connexion
        categories_stats = {
            "heures": {"total": 845, "evolution": 5.2, "trend": "up"},
            "rse": {"total": 124, "evolution": 12.8, "trend": "up"},
            "arion": {"total": 178, "evolution": 7.3, "trend": "up"},
            "vacataires": {"total": 42, "evolution": 3.1, "trend": "up"},
            "autres": {"total": 107, "evolution": -2.4, "trend": "down"}
        }
        
        quick_stats = {
            "heures_totales": 1254,
            "satisfaction": 86.0,
            "intervenants": 42,
            "innovations": 18
        }
        
    
    # Changement ici: catEnseug.html au lieu de catEnseig.html
    return render(request, 'statistiques/catEnseug.html', {
        'categories_stats': categories_stats,
        'quick_stats': quick_stats,
        'user_info': request.session.get('user_info', {})
    })

@api_authenticated_required
def heures_enseignement_upload_csv(request):
    """Vue pour importer un fichier CSV/Excel des heures d'enseignement"""
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
        
    # Vérifier si un fichier a été envoyé
    if 'file' not in request.FILES:
        return JsonResponse({"error": "Aucun fichier n'a été envoyé"}, status=400)
    
    file = request.FILES['file']
    
    # Vérifier l'extension du fichier
    if not (file.name.endswith('.csv') or file.name.endswith('.xlsx')):
        return JsonResponse({"error": "Seuls les fichiers CSV et Excel sont acceptés"}, status=400)
    
    try:
        # Préparer le fichier pour l'envoi à l'API Flask
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Envoyer le fichier et les données du formulaire
        files = {'file': (file.name, file.read(), 'application/octet-stream')}
        
        # Vous n'envoyez plus les paramètres supplémentaires, car ils seront extraits du fichier
        response = requests.post(
            f"{settings.API_URL}/heures-enseignement/upload",
            files=files,
            headers=headers,
            timeout=60  # Délai plus long pour les fichiers volumineux
        )
        
        logger.info(f"Réponse API: Status {response.status_code}")
        
        if response.status_code == 200:
            api_response = response.json()
            logger.info(f"Importation réussie: {api_response}")
            return JsonResponse({
                "success": True,
                "message": api_response.get('message', 'Fichier importé avec succès!'),
                "records_inserted": api_response.get('records_inserted', 0)
            })
        else:
            error_message = "Erreur lors de l'importation du fichier"
            try:
                api_response = response.json()
                logger.warning(f"Erreur API: {api_response}")
                error_message = api_response.get('error', error_message)
                if api_response.get('warning'):
                    return JsonResponse({"warning": api_response.get('warning')}, status=400)
            except Exception as e:
                logger.error(f"Erreur lors du parsing de la réponse API: {e}")
                
            return JsonResponse({"error": error_message}, status=response.status_code)
            
    except Exception as e:
        logger.error(f"Erreur lors de l'importation du fichier: {str(e)}")
        return JsonResponse({"error": f"Erreur lors de l'importation: {str(e)}"}, status=500)

@api_authenticated_required
def get_heures_enseignement_data(request):
    """API pour récupérer les données des heures d'enseignement"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données depuis l'API principale
        response = requests.get(f"{settings.API_URL}/heures-enseignement/data", headers=headers, timeout=10)
        
        if response.status_code == 200:
            return JsonResponse(response.json(), safe=False)
        else:
            return JsonResponse({'error': 'Erreur lors de la récupération des données'}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API heures_enseignement_data: {e}")
        return JsonResponse({'error': 'Erreur de connexion à API'}, status=500)

@api_authenticated_required
def get_heures_enseignement_graph_data(request):
    """Vue pour récupérer les données des graphiques des heures d'enseignement"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    # Récupérer les paramètres de filtrage
    annee_debut = request.GET.get('annee_debut', '')
    annee_fin = request.GET.get('annee_fin', '')
    niveau = request.GET.get('niveau', '')
    semestre = request.GET.get('semestre', '')
    
    try:
        # Construire l'URL avec les paramètres
        url = f"{settings.API_URL}/heures-enseignement/graph-data"
        params = {}
        
        if annee_debut:
            params['annee_debut'] = annee_debut
        if annee_fin:
            params['annee_fin'] = annee_fin
        if niveau:
            params['niveau'] = niveau
        if semestre:
            params['semestre'] = semestre
        
        # Appeler l'API
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            return JsonResponse(response.json(), safe=False)
        else:
            return JsonResponse({'error': 'Erreur lors de la récupération des données graphiques'}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API graph_data: {e}")
        return JsonResponse({'error': 'Erreur de connexion à l\'API'}, status=500)
#############################################################rse rse rse rse #####################################################################
@api_authenticated_required
def rse_view(request):
    """Vue principale pour la Responsabilité Sociétale des Entreprises (RSE)"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    stats = None
    rse_data = []
    
    try:
        # Récupérer les statistiques depuis l'API
        response = requests.get(f"{settings.API_URL}/rse/stats", headers=headers, timeout=10)
        if response.status_code == 200:
            stats = response.json()
            logger.info(f"Stats RSE récupérées: {stats.keys()}")
        else:
            logger.warning(f"Impossible de récupérer les stats RSE: Code {response.status_code}")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats RSE: {e}")
    
    try:
        # Récupérer les données détaillées
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        if response.status_code == 200:
            rse_data = response.json()
            logger.info(f"Données RSE récupérées: {len(rse_data)} enregistrements")
            
            # Extraire les promotions disponibles directement des données
            promotions_disponibles = sorted(list(set(item.get('promotion') for item in rse_data if item.get('promotion'))))
            
            # Si stats existe déjà, mettre à jour ou ajouter les promotions disponibles
            if stats:
                stats['promotions_disponibles'] = promotions_disponibles
            else:
                # Créer des statistiques de base si stats n'existe pas
                stats = {
                    'promotions_disponibles': promotions_disponibles
                }
                
            logger.info(f"Promotions disponibles: {promotions_disponibles}")
        else:
            logger.warning(f"Impossible de récupérer les données RSE: Code {response.status_code}")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des données RSE: {e}")
    
    # Liste des types d'activités RSE
    activites_maquette = [
        "Transition écologique et numérique",
        "Éthique informatique",
        "Développement durable",
        "Numérique responsable",
        "Accessibilité numérique",
        "Impact environnemental",
        "Diversité et inclusion",
        "Gouvernance responsable",
        "Autre"
    ]
    
    # Si pas de stats disponibles, créer des statistiques basiques à partir des données
    if not stats and rse_data:
        total_heures = sum(item.get('total_heures', 0) for item in rse_data)
        promotions = set(item.get('promotion') for item in rse_data if item.get('promotion'))
        
        stats = {
            'total_heures_rse': total_heures,
            'total_activites': len(rse_data),
            'promotions_impliquees': len(promotions),
            'etudiants_impliques': len(promotions) * 30,  # Estimation
            'promotions_disponibles': sorted(list(promotions)),
            'annees_disponibles': sorted(list(set(item.get('annee') for item in rse_data if item.get('annee'))))
        }
    
    # Pour les requêtes AJAX, renvoyer juste les données JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'stats': stats,
            'rse_data': rse_data
        })
    
    # Pour les requêtes normales, renvoyer la page HTML
    return render(request, 'statistiques/rse.html', {
        'stats': json.dumps(stats) if stats else "{}",
        'rse_data': rse_data,
        'activites_maquette': activites_maquette,
        'promotions_disponibles': promotions_disponibles
    })

@api_authenticated_required
def rse_add_data(request):
    """Vue pour ajouter/modifier des données RSE"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Méthode non autorisée'}, status=405)
    
    try:
        # Récupérer les données du formulaire
        data = {
            'id': request.POST.get('id'),
            'annee': request.POST.get('annee'),
            'promotion': request.POST.get('promotion'),
            'semestre': request.POST.get('semestre'),
            'type_activite': request.POST.get('type_activite'),
            'heures_cm': int(float(request.POST.get('heures_cm', 0) or 0)),
            'heures_td': int(float(request.POST.get('heures_td', 0) or 0)),
            'heures_tp': int(float(request.POST.get('heures_tp', 0) or 0)),
            'description': request.POST.get('description', '')
        }
        
        # Si le type est "Autre", utiliser la valeur spécifiée
        if data['type_activite'] == 'Autre':
            autre_type = request.POST.get('autre_type')
            if autre_type:
                data['type_activite'] = autre_type
        
        # Calculer le total des heures
        data['total_heures'] = data['heures_cm'] + data['heures_td'] + data['heures_tp']
        
        # Validation
        if not data['annee'] or not data['promotion'] or not data['semestre'] or not data['type_activite']:
            return JsonResponse({
                'success': False, 
                'message': 'Les champs année, promotion, semestre et type d\'activité sont obligatoires'
            }, status=400)
        
        if data['heures_cm'] == 0 and data['heures_td'] == 0 and data['heures_tp'] == 0:
            return JsonResponse({
                'success': False, 
                'message': 'Veuillez spécifier au moins un type d\'heures (CM, TD ou TP)'
            }, status=400)
        
        # Envoyer les données à l'API
        token = request.session.get('api_token')
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        if data['id']:  # Mise à jour
            url = f"{settings.API_URL}/rse/update"
        else:  # Nouvelle entrée
            url = f"{settings.API_URL}/rse/add"
            data.pop('id', None)  # Supprimer l'ID pour une nouvelle entrée
        
        response = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({
                'success': True,
                'message': api_response.get('message', 'Données RSE enregistrées avec succès!')
            })
        else:
            api_response = response.json()
            return JsonResponse({
                'success': False,
                'message': api_response.get('error', 'Erreur lors de l\'enregistrement des données RSE')
            }, status=response.status_code)
            
    except ValueError as e:
        logger.error(f"Erreur de conversion de valeur dans rse_add_data: {e}")
        return JsonResponse({
            'success': False,
            'message': f"Erreur de validation des données: {str(e)}"
        }, status=400)
    except Exception as e:
        logger.error(f"Erreur dans rse_add_data: {e}")
        return JsonResponse({
            'success': False,
            'message': f"Une erreur est survenue: {str(e)}"
        }, status=500)

def rse_delete_data(request, id):
    """Vue pour supprimer des données RSE"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Méthode non autorisée'}, status=405)
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.delete(
            f"{settings.API_URL}/rse/delete/{id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return JsonResponse({
                'success': True,
                'message': 'Données RSE supprimées avec succès!'
            })
        else:
            api_response = response.json()
            return JsonResponse({
                'success': False,
                'message': api_response.get('error', 'Erreur lors de la suppression des données RSE')
            }, status=response.status_code)
            
    except Exception as e:
        logger.error(f"Erreur dans rse_delete_data: {e}")
        return JsonResponse({
            'success': False,
            'message': f"Une erreur est survenue: {str(e)}"
        }, status=500)
    
@api_authenticated_required
def rse_upload_csv(request):
    """Vue pour importer un fichier CSV de données RSE"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Méthode non autorisée'}, status=405)
    
    try:
        # Vérifier le fichier
        if 'file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'message': 'Aucun fichier fourni'
            }, status=400)
        
        csv_file = request.FILES['file']
        
        # Vérifier l'extension du fichier
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({
                'success': False,
                'message': 'Le fichier doit être au format CSV'
            }, status=400)
        
        # Sauvegarder temporairement le fichier
        import tempfile
        import os
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
        temp_file.close()
        
        with open(temp_file.name, 'wb+') as destination:
            for chunk in csv_file.chunks():
                destination.write(chunk)
        
        # Traiter le fichier CSV
        result = process_rse_csv(temp_file.name)
        
        if not result['success']:
            return JsonResponse({
                'success': False,
                'message': f"Erreur lors du traitement du fichier CSV RSE: {result['error']}"
            }, status=400)
        
        # Envoyer les données à l'API
        token = request.session.get('api_token')
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            f"{settings.API_URL}/rse/bulk_add",
            json={'data': result['data']},
            headers=headers,
            timeout=30  # Délai plus long pour les imports volumineux
        )
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({
                'success': True,
                'message': f"Fichier CSV traité avec succès: {api_response.get('records_inserted', 0)} enregistrements importés",
                'warnings': result['errors'] if result['errors'] else []
            })
        else:
            try:
                api_response = response.json()
                error_msg = api_response.get('error', 'Erreur inconnue')
            except:
                error_msg = f"Erreur de communication avec l'API (Code: {response.status_code})"
            
            return JsonResponse({
                'success': False,
                'message': f"Erreur lors de l'importation: {error_msg}"
            }, status=500)
            
    except Exception as e:
        logger.error(f"Erreur dans rse_upload_csv: {e}")
        return JsonResponse({
            'success': False,
            'message': f"Erreur lors du traitement du fichier CSV RSE: {str(e)}"
        }, status=500)
    finally:
        # Nettoyer - supprimer le fichier temporaire
        if 'temp_file' in locals():
            try:
                os.unlink(temp_file.name)
            except:
                pass
def process_rse_csv(file_path):
    """
    Process a CSV file containing RSE data and safely convert values to appropriate types.
    Handles empty fields, NaN values, and other potential data issues.
    Also processes additional hour columns (heure1, heure2, heure3, heure4).
    """
    import pandas as pd
    import numpy as np
    import os
    
    # Read the CSV file using pandas
    try:
        # Try to guess the delimiter
        data = pd.read_csv(file_path, 
                          sep=None, 
                          engine='python', 
                          dtype=str,  # First read all as strings to avoid conversion errors
                          na_values=['', 'NA', 'N/A', 'nan', 'NaN'],
                          keep_default_na=True)
        
        # Validate required columns
        required_columns = ['annee', 'promotion', 'semestre', 'type_activite']
        numeric_columns = ['heures_cm', 'heures_td', 'heures_tp']
        additional_hours = ['heure1', 'heure2', 'heure3', 'heure4']
        
        # Check which additional hour columns are present
        present_additional_hours = [col for col in additional_hours if col in data.columns]
        
        # Add present additional hour columns to numeric columns for processing
        all_numeric_columns = numeric_columns + present_additional_hours
        
        # Check if required columns exist
        missing_columns = [col for col in required_columns if col not in data.columns]
        if missing_columns:
            return {
                'success': False, 
                'error': f"Colonnes manquantes dans le fichier CSV: {', '.join(missing_columns)}"
            }
        
        # Process and clean the data
        processed_data = []
        errors = []
        
        for index, row in data.iterrows():
            try:
                # Basic validation for required fields
                for col in required_columns:
                    if pd.isna(row[col]) or str(row[col]).strip() == '':
                        raise ValueError(f"La ligne {index+2} a une valeur manquante pour '{col}'")
                
                # Create a dictionary for this row
                record = {}
                
                # Process string fields
                record['annee'] = str(row['annee']).strip()
                record['promotion'] = str(row['promotion']).strip()
                record['semestre'] = str(row['semestre']).strip()
                record['type_activite'] = str(row['type_activite']).strip()
                
                # Add description if present
                if 'description' in row and not pd.isna(row['description']):
                    record['description'] = str(row['description']).strip()
                else:
                    record['description'] = ""
                
                # Process numeric fields with safe conversion
                for col in all_numeric_columns:
                    if col in row:
                        try:
                            # Handle missing or non-numeric values
                            if pd.isna(row[col]) or str(row[col]).strip() == '':
                                record[col] = 0  # Default to 0 for missing numeric values
                            else:
                                # Try to convert to float first, then to int
                                value = str(row[col]).strip().replace(',', '.')  # Handle commas as decimal separators
                                try:
                                    record[col] = int(float(value))
                                except ValueError:
                                    record[col] = 0
                                    errors.append(f"Ligne {index+2}: Valeur non numérique pour '{col}': '{value}' (0 utilisé)")
                        except Exception as e:
                            record[col] = 0  # Default to 0 on error
                            errors.append(f"Ligne {index+2}: Erreur lors du traitement de '{col}': {str(e)}")
                    else:
                        # Si la colonne est dans numeric_columns (obligatoire) mais pas dans les données
                        if col in numeric_columns:
                            record[col] = 0  # Default if column is missing
                
                # Calculate total hours (standard columns only)
                record['total_heures'] = record['heures_cm'] + record['heures_td'] + record['heures_tp']
                
                # Add the processed record
                processed_data.append(record)
                
            except Exception as e:
                errors.append(f"Erreur à la ligne {index+2}: {str(e)}")
        
        # Return the processed data and any errors
        return {
            'success': True,
            'data': processed_data,
            'errors': errors,
            'row_count': len(processed_data)
        }
        
    except Exception as e:
        # Handle file reading errors
        return {'success': False, 'error': f"Erreur lors de la lecture du fichier CSV: {str(e)}"}
    finally:
        # Clean up - remove the temporary file if needed
        if os.path.exists(file_path) and 'temp' in file_path:
            try:
                os.remove(file_path)
            except:
                pass
@api_authenticated_required
def get_rse_data(request):
    """API pour obtenir les données RSE filtrées par promotion"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    # Récupérer le paramètre de promotion s'il est spécifié
    promotion = request.GET.get('promotion', 'all')
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Filtrer par promotion si nécessaire
        if promotion != 'all':
            rse_data = [item for item in rse_data if item.get('promotion') == promotion]
        
        # Calculer les totaux pour les heures
        total_cm = sum(int(item.get('heures_cm', 0)) for item in rse_data)
        total_td = sum(int(item.get('heures_td', 0)) for item in rse_data)
        total_tp = sum(int(item.get('heures_tp', 0)) for item in rse_data)
        
        # Calculer les heures additionnelles si présentes
        additional_hours = {}
        for hour_type in ['heure1', 'heure2', 'heure3', 'heure4']:
            if any(hour_type in item for item in rse_data):
                additional_hours[hour_type] = sum(int(item.get(hour_type, 0)) for item in rse_data)
        
        # Extraire la liste des promotions disponibles
        promotions = list(set(item.get('promotion') for item in rse_data if item.get('promotion')))
        promotions.sort()  # Trier les promotions
        
        # Retourner les données au format JSON
        return JsonResponse({
            'data': {
                'heures_cm': total_cm,
                'heures_td': total_td,
                'heures_tp': total_tp,
                **additional_hours  # Inclure les heures additionnelles si présentes
            },
            'promotions': promotions
        })
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_data: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)

@api_authenticated_required
def get_rse_evolution_data(request):
    """API pour obtenir les données d'évolution des heures RSE par année"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Récupérer la liste des années disponibles
        annees = list(set(item.get('annee') for item in rse_data if item.get('annee')))
        annees.sort()  # Trier les années
        
        # Initialiser les données d'évolution
        evolution_data = []
        
        # Pour chaque année, calculer les totaux
        for annee in annees:
            # Filtrer les enregistrements pour cette année
            records = [item for item in rse_data if item.get('annee') == annee]
            
            # Calculer les totaux pour cette année
            total_cm = sum(int(item.get('heures_cm', 0)) for item in records)
            total_td = sum(int(item.get('heures_td', 0)) for item in records)
            total_tp = sum(int(item.get('heures_tp', 0)) for item in records)
            total = total_cm + total_td + total_tp
            
            # Ajouter à nos données d'évolution
            evolution_data.append({
                'annee': annee,
                'cm': total_cm,
                'td': total_td,
                'tp': total_tp,
                'total': total
            })
        
        return JsonResponse({
            'evolution_data': evolution_data
        })
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_evolution_data: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)

@api_authenticated_required
def get_rse_activity_types(request):
    """API pour obtenir la répartition des heures par type d'activité"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Créer un dictionnaire pour stocker les totaux par type d'activité
        type_totals = {}
        
        # Calculer les totaux par type d'activité
        for item in rse_data:
            type_activite = item.get('type_activite', 'Non spécifié')
            if type_activite not in type_totals:
                type_totals[type_activite] = 0
                
            # Ajouter les heures totales pour ce type
            heures_cm = int(item.get('heures_cm', 0))
            heures_td = int(item.get('heures_td', 0))
            heures_tp = int(item.get('heures_tp', 0))
            type_totals[type_activite] += heures_cm + heures_td + heures_tp
        
        # Convertir en liste pour le tri
        types_list = [{'type_activite': k, 'total_heures': v} for k, v in type_totals.items()]
        
        # Trier par total d'heures décroissant
        types_list.sort(key=lambda x: x['total_heures'], reverse=True)
        
        # Limiter à 8 types pour la lisibilité si nécessaire
        if len(types_list) > 8:
            # Conserver les 7 premiers types et regrouper les autres
            autres_total = sum(item['total_heures'] for item in types_list[7:])
            types_list = types_list[:7]
            types_list.append({
                'type_activite': 'Autres',
                'total_heures': autres_total
            })
        
        return JsonResponse({
            'types_data': types_list
        })
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_activity_types: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)

@api_authenticated_required
def get_rse_format_cours(request):
    """API pour obtenir la répartition globale CM/TD/TP"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Calculer les totaux
        total_cm = sum(int(item.get('heures_cm', 0)) for item in rse_data)
        total_td = sum(int(item.get('heures_td', 0)) for item in rse_data)
        total_tp = sum(int(item.get('heures_tp', 0)) for item in rse_data)
        
        # Calculer les pourcentages
        total = total_cm + total_td + total_tp
        
        if total > 0:
            percent_cm = (total_cm / total) * 100
            percent_td = (total_td / total) * 100
            percent_tp = (total_tp / total) * 100
        else:
            percent_cm = percent_td = percent_tp = 0
        
        return JsonResponse({
            'total_cm': total_cm,
            'total_td': total_td,
            'total_tp': total_tp,
            'percent_cm': round(percent_cm, 1),
            'percent_td': round(percent_td, 1),
            'percent_tp': round(percent_tp, 1)
        })
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_format_cours: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)

@api_authenticated_required
def get_rse_hours_by_promotion(request):
    """API pour obtenir les heures RSE totales par promotion"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Créer un dictionnaire pour stocker les totaux par promotion
        promotion_totals = {}
        
        # Calculer les totaux par promotion
        for item in rse_data:
            promotion = item.get('promotion')
            if not promotion:
                continue
                
            if promotion not in promotion_totals:
                promotion_totals[promotion] = 0
                
            # Ajouter les heures totales pour cette promotion
            heures_cm = int(item.get('heures_cm', 0))
            heures_td = int(item.get('heures_td', 0))
            heures_tp = int(item.get('heures_tp', 0))
            
            # Ajouter les heures additionnelles si présentes
            additional_hours = 0
            for hour_key in ['heure1', 'heure2', 'heure3', 'heure4']:
                if hour_key in item:
                    additional_hours += int(item.get(hour_key, 0))
            
            promotion_totals[promotion] += heures_cm + heures_td + heures_tp + additional_hours
        
        # Convertir en liste pour le tri
        promotions_list = [{'promotion': k, 'total_heures': v} for k, v in promotion_totals.items()]
        
        # Trier par nom de promotion
        promotions_list.sort(key=lambda x: x['promotion'])
        
        return JsonResponse({
            'promotions_data': promotions_list
        })
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_hours_by_promotion: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)

@api_authenticated_required
def get_rse_item(request, id):
    """API pour obtenir les détails d'un élément RSE spécifique"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données RSE complètes
        response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if response.status_code != 200:
            return JsonResponse({'error': 'Erreur lors de la récupération des données RSE'}, status=response.status_code)
        
        # Traiter les données
        rse_data = response.json()
        
        # Trouver l'élément avec l'ID spécifié
        item = next((item for item in rse_data if item.get('id') == id), None)
        
        if not item:
            return JsonResponse({'error': f'Aucun élément RSE trouvé avec l\'ID {id}'}, status=404)
        
        return JsonResponse(item)
        
    except Exception as e:
        logger.error(f"Erreur dans get_rse_item: {e}")
        return JsonResponse({'error': f"Une erreur est survenue: {str(e)}"}, status=500)
################################################################################################### ARION #############################
@api_authenticated_required
def arion(request):
    """Vue pour afficher l'interface ARION"""
    context = {
        'page_title': 'ARION - Recherche',
        'active_tab': 'arion'
    }
    return render(request, 'statistiques/arion.html', context)

@csrf_exempt
@api_authenticated_required
def arion_api_redirect(request):
    """Redirection vers l'API Flask pour les endpoints ARION"""
    # Construire l'URL Flask
    path = request.path
    flask_url = f"{FLASK_API_URL}{path}"
    
    try:
        # Gérer les différentes méthodes HTTP
        if request.method == 'GET':
            # Transmettre les paramètres de requête GET
            params = request.GET.dict()
            response = requests.get(flask_url, params=params)
        elif request.method == 'POST':
            # Vérifier s'il s'agit d'un formulaire multipart ou de données JSON
            if request.content_type and 'multipart/form-data' in request.content_type:
                # Cas de l'upload de fichier CSV
                files = {'file': request.FILES['file']} if 'file' in request.FILES else None
                data = request.POST.dict()
                response = requests.post(flask_url, files=files, data=data)
            else:
                # Cas des données JSON
                try:
                    data = json.loads(request.body)
                    response = requests.post(flask_url, json=data)
                except json.JSONDecodeError:
                    response = requests.post(flask_url, data=request.body)
        else:
            # Méthode non supportée
            return JsonResponse({"error": f"Méthode {request.method} non supportée"}, status=405)
        
        # Retourner la réponse du serveur Flask
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
    except Exception as e:
        return JsonResponse({"error": f"Erreur de connexion au serveur API: {str(e)}"}, status=500)

@csrf_exempt
@api_authenticated_required
def arion_api_stats(request):
    """Redirection vers l'API Flask pour les statistiques ARION"""
    try:
        # Construire l'URL Flask
        flask_url = f"{FLASK_API_URL}/api/arion/stats"
        
        # Faire la requête à l'API Flask
        response = requests.get(flask_url)
        
        # Retourner la réponse du serveur Flask
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
    except Exception as e:
        return JsonResponse({"error": f"Erreur de connexion au serveur API: {str(e)}"}), 500

@csrf_exempt
@api_authenticated_required
def arion_api_add(request):
    """Redirection vers l'API Flask pour ajouter des données ARION"""
    try:
        # Construire l'URL Flask
        flask_url = f"{FLASK_API_URL}/api/arion/add"
        
        # Extraire le contenu JSON de la requête
        data = json.loads(request.body)
        
        # Faire la requête à l'API Flask
        response = requests.post(flask_url, json=data)
        
        # Retourner la réponse du serveur Flask
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
    except Exception as e:
        return JsonResponse({"error": f"Erreur de connexion au serveur API: {str(e)}"}), 500

@csrf_exempt
@api_authenticated_required
def arion_api_delete(request, item_id):
    """Redirection vers l'API Flask pour supprimer des données ARION"""
    try:
        # Construire l'URL Flask
        flask_url = f"{FLASK_API_URL}/api/arion/delete/{item_id}"
        
        # Faire la requête à l'API Flask
        response = requests.delete(flask_url)
        
        # Retourner la réponse du serveur Flask
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
    except Exception as e:
        return JsonResponse({"error": f"Erreur de connexion au serveur API: {str(e)}"}, status=500)

@csrf_exempt
@api_authenticated_required
def arion_api_upload(request):
    """Redirection vers l'API Flask pour l'upload CSV ARION"""
    try:
        # Construire l'URL Flask
        flask_url = f"{FLASK_API_URL}/api/arion/upload"
        
        # Extraire le fichier et les données du formulaire
        file = request.FILES.get('file')
        annee_import = request.POST.get('annee_import')
        
        # Préparer les données pour la requête multipart
        files = {'file': (file.name, file.read(), file.content_type)}
        data = {'annee_import': annee_import} if annee_import else {}
        
        # Faire la requête à l'API Flask
        response = requests.post(flask_url, files=files, data=data)
        
        # Retourner la réponse du serveur Flask
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )
    except Exception as e:
        return JsonResponse({"error": f"Erreur de connexion au serveur API: {str(e)}"}), 500

@api_authenticated_required
def arion_status_stats(request):
    """Vue pour obtenir les statistiques par statut des formateurs sans répétition"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Appel à l'API Flask pour obtenir les données
        response = requests.get(f"{settings.API_URL}/arion/data", headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Récupérer les données
            data = response.json()
            
            # Utiliser un dictionnaire pour suivre les formateurs uniques par statut
            formateurs_par_statut = {}
            
            for item in data:
                # Extraire le formateur et le statut
                formateur = item.get('formateur')
                statut = item.get('statut', 'Non spécifié')
                
                # Standardiser les statuts pour éviter les variations mineures
                if statut == 'Vacataire':
                    statut = 'Vacataires'
                elif not statut or statut.lower() == 'non spécifié':
                    statut = 'Non spécifié'
                
                # Initialiser le dictionnaire pour ce statut si nécessaire
                if statut not in formateurs_par_statut:
                    formateurs_par_statut[statut] = set()
                
                # Ajouter le formateur à l'ensemble pour ce statut (les ensembles éliminent les doublons)
                if formateur:
                    formateurs_par_statut[statut].add(formateur)
            
            # Calculer le nombre de formateurs uniques par statut
            status_stats = {
                "labels": list(formateurs_par_statut.keys()),
                "values": [len(formateurs) for formateurs in formateurs_par_statut.values()]
            }
            
            return JsonResponse({
                'success': True,
                'status_stats': status_stats
            })
        else:
            # En cas d'erreur, renvoyer un message approprié
            return JsonResponse({
                'success': False,
                'error': f"Erreur lors de la récupération des données: {response.status_code}"
            }, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        return JsonResponse({
            'success': False,
            'error': f"Erreur de connexion à l'API: {str(e)}"
        }, status=500)

@api_authenticated_required
def arion_monthly_stats(request):
    try:
        # Récupérer le paramètre d'année optionnel
        selected_year = request.GET.get('year', None)
        
        # Ajouter un cache pour les données récentes
        cache_key = f"arion_monthly_stats_{selected_year or 'all'}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return JsonResponse(cached_data)
        
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Ajouter des paramètres de pagination et limiter les données
        # Faire la requête à l'API Flask pour récupérer les données
        response = requests.get(
            f"{settings.API_URL}/arion/data", 
            headers=headers, 
            params={'limit': 500},  # Limiter à 500 résultats pour améliorer les performances
            timeout=5  # Réduire le timeout
        )
        
        if response.status_code != 200:
            return JsonResponse({"error": "Impossible de récupérer les données"}, status=response.status_code)
        
        # Obtenir les données
        data = response.json()
        
        # Initialiser les compteurs pour chaque mois
        monthly_counts = {month: 0 for month in range(1, 13)}
        
        # Parcourir les données et compter les activités par mois
        for item in data:
            # Vérifier si la date est valide
            if 'date' in item and item['date']:
                try:
                    # La date est au format YYYY-MM-DD
                    date_parts = item['date'].split('-')
                    if len(date_parts) == 3:
                        year = date_parts[0]
                        month = int(date_parts[1])
                        
                        # Filtrer par année si spécifiée
                        if selected_year and year != selected_year:
                            continue
                            
                        # Incrémenter le compteur pour ce mois
                        if month in monthly_counts:
                            monthly_counts[month] += 1
                except Exception as e:
                    # Ne pas surcharger les logs
                    pass
        
        # Préparer les données pour le graphique
        month_names = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
        values = [monthly_counts[month] for month in range(1, 13)]
        
        result = {
            "labels": month_names,
            "values": values
        }
        
        # Stocker dans le cache pour 10 minutes (600 secondes)
        cache.set(cache_key, result, 600)
        
        return JsonResponse(result)
    
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques mensuelles: {str(e)}")
        return JsonResponse({"error": f"Erreur lors de la récupération des statistiques mensuelles: {str(e)}"}, status=500)
    
###################################### VACATAIRE ####################################
@api_authenticated_required
def vacataire(request):
    """Vue pour la page des vacataires"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données des vacataires depuis l'API
        response = requests.get(f"{settings.API_URL}/vacataire/data", headers=headers, timeout=10)
        if response.status_code == 200:
            vacataires_data = response.json()
            logger.info(f"Données vacataires récupérées: {len(vacataires_data)} enregistrements")
        else:
            vacataires_data = []
            logger.warning(f"Impossible de récupérer les données vacataires: Code {response.status_code}")
            messages.warning(request, "Impossible de récupérer les données des vacataires.")
    except requests.exceptions.RequestException as e:
        vacataires_data = []
        logger.error(f"Erreur API vacataire: {e}")
        messages.error(request, "Erreur de connexion à l'API pour récupérer les données des vacataires.")
    
    return render(request, 'statistiques/vacataire.html', {
        'user_info': request.session.get('user_info', {}),
        'vacataires_data': json.dumps(vacataires_data)
    })
@api_authenticated_required
def vacataire_data(request):
    """Vue pour récupérer les données des vacataires"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données des vacataires depuis l'API
        response = requests.get(f"{settings.API_URL}/vacataire/data", headers=headers, timeout=10)
        if response.status_code == 200:
            vacataires_data = response.json()
            logger.info(f"Données vacataires récupérées: {len(vacataires_data)} enregistrements")
            return JsonResponse(vacataires_data, safe=False)
        else:
            logger.warning(f"Impossible de récupérer les données vacataires: Code {response.status_code}")
            return JsonResponse([], safe=False)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_data: {e}")
        return JsonResponse([], safe=False)
    
@api_authenticated_required
def vacataire_stats(request):
    """Vue pour récupérer les statistiques des vacataires"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les statistiques des vacataires depuis l'API
        response = requests.get(f"{settings.API_URL}/vacataire/stats", headers=headers, timeout=10)
        if response.status_code == 200:
            stats_data = response.json()
            logger.info("Statistiques vacataires récupérées avec succès")
            return JsonResponse(stats_data)
        else:
            logger.warning(f"Impossible de récupérer les statistiques vacataires: Code {response.status_code}")
            
            # Créer des statistiques vides si l'API ne renvoie pas de données
            empty_stats = {
                "profession": {"labels": [], "values": []},
                "pays": {"labels": [], "values": []},
                "etat_recrutement": {"labels": [], "values": []},
                "heures": {"labels": [], "values": []}
            }
            return JsonResponse(empty_stats)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_stats: {e}")
        
        # Créer des statistiques vides en cas d'erreur
        empty_stats = {
            "profession": {"labels": [], "values": []},
            "pays": {"labels": [], "values": []},
            "etat_recrutement": {"labels": [], "values": []},
            "heures": {"labels": [], "values": []}
        }
        return JsonResponse(empty_stats)
    
@api_authenticated_required
def vacataire_add_data(request):
    """Vue pour ajouter un vacataire manuellement"""
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données du formulaire
        data = request.POST.dict()
        
        # Envoyer les données à l'API
        response = requests.post(
            f"{settings.API_URL}/vacataire/add",
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code == 201:
            return JsonResponse({"success": True, "message": "Vacataire ajouté avec succès"})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur inconnue')}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_add_data: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de l'ajout du vacataire."}, status=500)

@api_authenticated_required
def vacataire_upload_csv(request):
    """Vue pour uploader un fichier CSV de vacataires"""
    if request.method != 'POST' or not request.FILES.get('csvFile'):
        return JsonResponse({"error": "Fichier CSV requis"}, status=400)
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    csv_file = request.FILES['csvFile']
    
    try:
        # Vérifier l'extension du fichier
        if not csv_file.name.endswith('.csv'):
            return JsonResponse({"error": "Le fichier doit être au format CSV"}, status=400)
        
        # Lire les premières lignes du fichier pour le log
        file_content = csv_file.read(1024).decode('utf-8', errors='replace')
        logger.info(f"Début du contenu CSV: {file_content[:200]}...")
        
        # Réinitialiser le pointeur du fichier
        csv_file.seek(0)
        
        # Envoyer le fichier à l'API
        files = {'file': (csv_file.name, csv_file, 'text/csv')}
        
        response = requests.post(
            f"{settings.API_URL}/vacataire/upload-csv",
            headers=headers,
            files=files,
            timeout=60  # Délai plus long pour l'upload
        )
        
        logger.info(f"Réponse API upload CSV: Status {response.status_code}")
        
        if response.status_code == 200:
            api_response = response.json()
            return JsonResponse({
                "success": True, 
                "message": f"{api_response.get('records_inserted', 0)} enregistrements ajoutés."
            })
        else:
            try:
                api_response = response.json()
                error_msg = api_response.get('error', 'Erreur inconnue')
                logger.error(f"Erreur API: {error_msg}")
                return JsonResponse({"error": error_msg}, status=response.status_code)
            except:
                logger.error(f"Réponse API non-JSON: {response.text}")
                return JsonResponse({"error": f"Erreur serveur: {response.status_code}"}, status=response.status_code)
            
    except UnicodeDecodeError as e:
        logger.error(f"Erreur d'encodage: {e}")
        return JsonResponse({"error": "Le fichier CSV a un problème d'encodage. Assurez-vous qu'il est encodé en UTF-8."}, status=400)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur upload API vacataire: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de l'upload du fichier."}, status=500)
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        return JsonResponse({"error": f"Une erreur inattendue s'est produite: {str(e)}"}, status=500)
    finally:
        if hasattr(csv_file, 'file') and hasattr(csv_file.file, 'close'):
            csv_file.file.close()

@api_authenticated_required
def vacataire_delete(request, id):
    """Vue pour supprimer un vacataire"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.delete(
            f"{settings.API_URL}/vacataire/delete/{id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return JsonResponse({"success": True, "message": "Vacataire supprimé avec succès"})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur lors de la suppression')}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_delete: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de la suppression du vacataire."}, status=500)

@api_authenticated_required
def vacataire_update(request, id):
    """Vue pour mettre à jour un vacataire"""
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
    
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        # Récupérer les données du formulaire
        data = request.POST.dict()
        
        # Envoyer les données à l'API
        response = requests.put(
            f"{settings.API_URL}/vacataire/update/{id}",
            headers=headers,
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            return JsonResponse({"success": True, "message": "Vacataire mis à jour avec succès"})
        else:
            api_response = response.json()
            return JsonResponse({"error": api_response.get('error', 'Erreur inconnue')}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_update: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de la mise à jour du vacataire."}, status=500)

@api_authenticated_required
def vacataire_stats(request):
    """Vue pour récupérer les statistiques des vacataires"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(f"{settings.API_URL}/vacataire/stats", headers=headers, timeout=10)
        
        if response.status_code == 200:
            stats_data = response.json()
            return JsonResponse(stats_data)
        else:
            return JsonResponse({"error": "Impossible de récupérer les statistiques"}, status=response.status_code)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API vacataire_stats: {e}")
        return JsonResponse({"error": "Erreur de connexion lors de la récupération des statistiques."}, status=500)


################################################## cat special########################
@api_authenticated_required
def cat_special(request):
    """Vue principale pour les catégories spéciales"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    return render(request, 'statistiques/catSpecial.html', {
        'user_info': request.session.get('user_info', {}),
        'settings': settings
    })

@api_authenticated_required
def cat_special_upload_csv(request):
    """Vue pour importer un fichier CSV des catégories spéciales"""
    if request.method != 'POST':
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)
        
    # Vérifier si un fichier a été envoyé
    if 'file' not in request.FILES:
        return JsonResponse({"error": "Aucun fichier n'a été envoyé"}, status=400)
    
    file = request.FILES['file']
    
    # Vérifier l'extension du fichier
    if not file.name.endswith('.csv'):
        return JsonResponse({"error": "Seuls les fichiers CSV sont acceptés"}, status=400)
    
    try:
        # Préparer le fichier pour l'envoi à l'API Flask
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Envoyer le fichier à l'API
        files = {'file': (file.name, file.read(), 'application/octet-stream')}
        
        response = requests.post(
            f"{settings.API_URL}/cat-special/upload",
            files=files,
            headers=headers,
            timeout=60  # Délai plus long pour les fichiers volumineux
        )
        
        logger.info(f"Réponse API: Status {response.status_code}")
        
        if response.status_code == 200:
            api_response = response.json()
            logger.info(f"Importation réussie: {api_response}")
            return JsonResponse({
                "success": True,
                "message": api_response.get('message', 'Fichier importé avec succès!'),
                "records_inserted": api_response.get('records_inserted', 0)
            })
        else:
            try:
                error_msg = response.json().get('error', 'Erreur inconnue')
                logger.error(f"Erreur API: {error_msg}")
                return JsonResponse({"error": error_msg}, status=response.status_code)
            except:
                logger.error(f"Erreur API non-JSON: {response.text}")
                return JsonResponse({"error": f"Erreur lors de l'importation (Code: {response.status_code})"}, status=500)
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'envoi de la requête API: {e}")
        return JsonResponse({"error": f"Erreur de connexion à l'API: {str(e)}"}, status=500)
    except Exception as e:
        logger.error(f"Erreur imprévue: {e}")
        return JsonResponse({"error": f"Erreur lors du traitement du fichier: {str(e)}"}, status=500)

@api_authenticated_required
def get_cat_special_data(request):
    """Vue pour récupérer les données des catégories spéciales"""
    try:
        token = request.session.get('api_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Ajout du préfixe /api si nécessaire
        response = requests.get(
            f"{settings.API_URL}/api/cat-special",  # Notez le /api ajouté ici
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            return JsonResponse(response.json())
        else:
            return JsonResponse({"error": "Erreur lors de la récupération des données"}, status=response.status_code)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des données: {e}")
        return JsonResponse({"error": str(e)}, status=500)