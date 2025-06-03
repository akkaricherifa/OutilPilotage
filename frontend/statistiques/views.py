# statistiques/views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.views.decorators.csrf import csrf_exempt
from .forms import CSVUploadForm, UserRegisterForm, DataUpdateForm
from .models import CSVFile, UserRole
import requests
import json
import logging

logger = logging.getLogger(__name__)

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