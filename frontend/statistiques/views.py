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
                messages.success(request, 'Compte créé avec succès! Vous pouvez maintenant vous connecter.')
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
            messages.warning(request, f"Impossible de récupérer les statistiques (Code: {response.status_code})")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API dashboard: {e}")
        statistics = None
        messages.error(request, "Erreur de connexion à l'API pour récupérer les statistiques.")
    
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
        else:
            users_data = []
            api_response = response.json()
            messages.error(request, f"Erreur API: {api_response.get('error', 'Impossible de récupérer les utilisateurs')}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API admin_users: {e}")
        users_data = []
        messages.error(request, "Erreur de connexion pour récupérer les utilisateurs.")
    
    return render(request, 'statistiques/admin_users.html', {'users_data': users_data})

@api_authenticated_required
def effectifs_etudiants(request):
    """Vue principale pour les effectifs étudiants - CORRIGÉE"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    stats = None
    all_data = []
    
    try:
        # Récupérer les statistiques depuis l'API
        response = requests.get(f"{settings.API_URL}/effectifs/stats", headers=headers, timeout=10)
        if response.status_code == 200:
            stats = response.json()
        else:
            # Si l'endpoint n'existe pas, essayer l'endpoint général
            logger.info("Endpoint /effectifs/stats non disponible, utilisation de /statistics")
            
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats effectifs: {e}")
    
    try:
        # Récupérer toutes les données pour le tableau
        response = requests.get(f"{settings.API_URL}/effectifs", headers=headers, timeout=10)
        if response.status_code == 200:
            all_data = response.json()
        else:
            # Si l'endpoint n'existe pas, essayer l'endpoint général
            logger.info("Endpoint /effectifs non disponible, utilisation de /data")
            response = requests.get(f"{settings.API_URL}/data", headers=headers, timeout=10)
            if response.status_code == 200:
                all_data = response.json()
                
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des données effectifs: {e}")
    
    # Si stats est None mais all_data contient des données, générer des statistiques basiques
    if stats is None and all_data:
        try:
            # Créer des statistiques basiques à partir de all_data
            total_fie1 = sum(item.get('nombre_fie1', 0) for item in all_data)
            total_fie2 = sum(item.get('nombre_fie2', 0) for item in all_data)
            total_fie3 = sum(item.get('nombre_fie3', 0) for item in all_data)
            total_diplomes = sum(item.get('nombre_diplomes', 0) for item in all_data)
            
            # Calculer la moyenne des taux de boursiers
            taux_boursiers_list = [item.get('taux_boursiers', 0) for item in all_data if item.get('taux_boursiers') is not None]
            avg_taux_boursiers = sum(taux_boursiers_list) / len(taux_boursiers_list) if taux_boursiers_list else 0
            
            # Créer un objet stats basique
            stats = {
                "total_students": {
                    "fie1": total_fie1,
                    "fie2": total_fie2,
                    "fie3": total_fie3,
                },
                "avg_taux_boursiers": avg_taux_boursiers * 100,  # En pourcentage
                "total_diplomes": total_diplomes,
                "evolution_annuelle": sorted(all_data, key=lambda x: x.get('annee', 0))
            }
        except Exception as e:
            logger.error(f"Erreur lors de la génération des statistiques: {e}")
            messages.error(request, f"Erreur lors de la génération des statistiques: {str(e)}")
    
    # Si toujours pas de données, afficher un message d'information
    if not stats and not all_data:
        messages.info(request, "Aucune donnée d'effectifs disponible. Commencez par importer un fichier CSV ou ajouter des données manuellement.")
    
    return render(request, 'statistiques/effectifs_etudiants.html', {
        'stats': stats,
        'all_data': all_data
    })

######################################## CATEGORIE ENSEIGNEMENT ##############################################

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
            messages.warning(request, f"Erreur API: {api_response.get('error', 'Impossible de récupérer les statistiques des catégories d\'enseignement')}")
            
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
        
        messages.error(request, "Erreur de connexion à l'API pour récupérer les statistiques des catégories d'enseignement.")
    
    # Changement ici: catEnseug.html au lieu de catEnseig.html
    return render(request, 'statistiques/catEnseug.html', {
        'categories_stats': categories_stats,
        'quick_stats': quick_stats,
        'user_info': request.session.get('user_info', {})
    })
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
############################rse rse rse rse #################
@api_authenticated_required
def rse_view(request):
    """Vue principale pour les données RSE"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    # Liste des types d'activités RSE prédéfinis
    activites_maquette = [
        "Transition écologique et numérique",
        "Responsabilité sociale et environnementale de l'ingénieur",
        "Anthropocène",
        "Numérique responsable",
        "Enjeux socio environnementaux",
        "Autre"
    ]
    
    # Valeurs par défaut au cas où les requêtes API échouent
    stats = {"items": []}
    rse_data = []
    
    try:
        # Récupérer d'abord les données complètes
        logger.info("Récupération des données RSE depuis l'API")
        data_response = requests.get(f"{settings.API_URL}/rse/data", headers=headers, timeout=10)
        
        if data_response.status_code == 200:
            rse_data = data_response.json()
            logger.info(f"Données RSE récupérées: {len(rse_data)} enregistrements")
            
            # Nettoyer les données pour éviter les valeurs non-JSON
            rse_data = clean_json_data(rse_data)
            
            # Extraire les promotions pour débogage
            promotions = set([item.get('promotion') for item in rse_data if 'promotion' in item])
            logger.info(f"Promotions dans les données: {promotions}")
        else:
            logger.warning(f"Erreur API data RSE: {data_response.status_code} - {data_response.text}")
            messages.warning(request, "Impossible de récupérer les données RSE.")
        
        # Récupérer ensuite les statistiques
        logger.info("Récupération des statistiques RSE depuis l'API")
        stats_response = requests.get(f"{settings.API_URL}/rse/stats", headers=headers, timeout=10)
        
        if stats_response.status_code == 200:
            stats = stats_response.json()
            logger.info(f"Statistiques RSE récupérées avec les clés: {list(stats.keys())}")
            
            # Nettoyer les statistiques pour éviter les valeurs non-JSON
            stats = clean_json_data(stats)
            
            # S'assurer que les items sont inclus dans les stats
            if 'items' not in stats and rse_data:
                logger.info("Ajout des données RSE aux statistiques car 'items' est manquant")
                stats['items'] = rse_data
            
            # S'assurer que la liste des promotions est complète
            if rse_data and 'promotions_disponibles' not in stats:
                logger.info("Génération de la liste des promotions disponibles")
                promotions_set = set()
                for item in rse_data:
                    if item.get('promotion'):
                        promotions_set.add(item.get('promotion'))
                
                stats['promotions_disponibles'] = sorted(list(promotions_set))
                logger.info(f"Promotions générées: {stats['promotions_disponibles']}")
        else:
            logger.warning(f"Erreur API stats RSE: {stats_response.status_code} - {stats_response.text}")
            
            # Construire des statistiques minimales à partir des données
            if rse_data:
                logger.info("Construction de statistiques de base à partir des données RSE")
                
                # Extraire les promotions
                promotions_set = set()
                for item in rse_data:
                    if item.get('promotion'):
                        promotions_set.add(item.get('promotion'))
                
                # Calculer les totaux
                total_cm = sum(item.get('heures_cm', 0) for item in rse_data)
                total_td = sum(item.get('heures_td', 0) for item in rse_data)
                total_tp = sum(item.get('heures_tp', 0) for item in rse_data)
                total_heures = total_cm + total_td + total_tp
                
                # Construire l'objet stats
                stats = {
                    "items": rse_data,
                    "total_heures_rse": total_heures,
                    "total_activites": len(rse_data),
                    "promotions_impliquees": len(promotions_set),
                    "etudiants_impliques": 342,  # Valeur par défaut
                    "promotions_disponibles": sorted(list(promotions_set)),
                    "format_cours_pourcentage": {
                        'CM': round(total_cm / total_heures * 100 if total_heures > 0 else 0, 1),
                        'TD': round(total_td / total_heures * 100 if total_heures > 0 else 0, 1),
                        'TP': round(total_tp / total_heures * 100 if total_heures > 0 else 0, 1)
                    },
                    "graphiques": {
                        'format_cours': {
                            'labels': ['CM', 'TD', 'TP'],
                            'values': [total_cm, total_td, total_tp]
                        }
                    }
                }
                
                logger.info("Statistiques de base construites avec succès")
            else:
                stats = {"items": []}
                messages.warning(request, "Impossible de récupérer les statistiques RSE.")
        
        # Si c'est une requête AJAX, renvoyer les données en JSON
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logger.info("Requête AJAX détectée, renvoi des données JSON")
            return JsonResponse(stats)
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion lors de la récupération des données RSE: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': str(e), 'details': 'Erreur de connexion à l\'API'}, status=500)
            
        messages.error(request, f"Erreur de connexion à l'API RSE: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue dans rse_view: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': str(e), 'details': 'Erreur inattendue'}, status=500)
            
        messages.error(request, f"Une erreur inattendue s'est produite: {str(e)}")
    
    # Préparer les données pour le template en convertissant stats en JSON
    try:
        # Double vérification des valeurs problématiques
        stats = clean_json_data(stats)
        stats_json = json.dumps(stats)
        logger.info("Conversion des statistiques en JSON réussie")
    except Exception as e:
        logger.error(f"Erreur lors de la conversion des stats en JSON: {e}")
        # En cas d'erreur, créer un JSON minimal
        stats_json = json.dumps({"items": []})
        messages.error(request, "Erreur lors du traitement des données RSE pour l'affichage")
    
    return render(request, 'statistiques/rse.html', {
        'stats': stats_json,
        'rse_data': rse_data,
        'activites_maquette': activites_maquette,
        'user_info': request.session.get('user_info', {})
    })
@api_authenticated_required
def rse_add_data(request):
    """Vue pour ajouter/modifier des données RSE"""
    if request.method != 'POST':
        return redirect('rse')
    
    token = request.session.get('api_token')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    try:
        # Traiter les données du formulaire
        data = {
            'id': request.POST.get('id', ''),
            'annee': int(request.POST.get('annee', 0)),
            'promotion': request.POST.get('promotion', ''),
            'semestre': request.POST.get('semestre', ''),
            'heures_cm': int(request.POST.get('heures_cm', 0)),
            'heures_td': int(request.POST.get('heures_td', 0)),
            'heures_tp': int(request.POST.get('heures_tp', 0))
        }
        
        # Gérer le type d'activité (standard ou personnalisé)
        type_activite = request.POST.get('type_activite', '')
        if type_activite == 'Autre':
            data['type_activite'] = request.POST.get('autre_type', '')
        else:
            data['type_activite'] = type_activite
            
        # Ajouter une description si disponible
        if request.POST.get('description'):
            data['description'] = request.POST.get('description')
        
        # Déterminer si c'est un ajout ou une mise à jour
        if data['id']:
            url = f"{settings.API_URL}/rse/update"
            message_success = "Données RSE mises à jour avec succès!"
        else:
            url = f"{settings.API_URL}/rse/add"
            message_success = "Nouvelles données RSE ajoutées avec succès!"
        
        # Envoyer à l'API
        response = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=10
        )
        
        # Journaliser la réponse pour débogage
        logger.info(f"Réponse API RSE: {response.status_code} - {response.text}")
        
        if response.status_code == 200:
            # Gestion des requêtes AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': message_success})
            
            messages.success(request, message_success)
            return redirect('rse')
        else:
            try:
                error_data = response.json()
                error_message = error_data.get('error', 'Erreur inconnue')
            except:
                error_message = f"Erreur API (code {response.status_code})"
            
            logger.error(f"Erreur API lors de l'ajout RSE: {error_message}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': error_message}, status=400)
            
            messages.error(request, f"Erreur lors de l'enregistrement: {error_message}")
            
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout/modification RSE: {e}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
        
        messages.error(request, f"Une erreur est survenue: {str(e)}")
    
    return redirect('rse')
@api_authenticated_required
def rse_delete_data(request, rse_id):
    """Vue pour supprimer des données RSE"""
    token = request.session.get('api_token')
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.delete(
            f"{settings.API_URL}/rse/delete/{rse_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"success": True, "message": "Données RSE supprimées avec succès!"})
            
            messages.success(request, "Données RSE supprimées avec succès!")
            return redirect('rse')
        else:
            api_response = response.json()
            error_message = api_response.get('error', 'Erreur lors de la suppression des données RSE.')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"error": error_message}, status=response.status_code)
            
            messages.error(request, error_message)
            return redirect('rse')
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API rse_delete_data: {e}")
        error_message = "Erreur de connexion lors de la suppression des données RSE."
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"error": error_message}, status=500)
        
        messages.error(request, error_message)
        return redirect('rse')
    


############ ARION #############################
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