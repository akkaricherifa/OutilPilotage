// À placer dans un fichier static/js/ajax-utils.js
// Fonctions utilitaires pour les requêtes AJAX avec authentification

// Fonction pour récupérer le token JWT depuis la session ou localStorage
function getApiToken() {
    // Essayer d'abord dans sessionStorage (meilleure pratique)
    const sessionToken = sessionStorage.getItem('api_token');
    if (sessionToken) {
        return sessionToken;
    }
    
    // Ensuite, essayer dans localStorage (moins sécurisé)
    const localToken = localStorage.getItem('api_token');
    if (localToken) {
        return localToken;
    }
    
    // Enfin, essayer de récupérer depuis Django session (via un attribut data)
    const djangoToken = document.body.getAttribute('data-api-token');
    if (djangoToken) {
        // Stocker dans sessionStorage pour les requêtes futures
        sessionStorage.setItem('api_token', djangoToken);
        return djangoToken;
    }
    
    return null;
}

// Fonction pour récupérer le CSRF token Django
function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
}

// Fonction pour préparer les headers d'une requête AJAX
function prepareAjaxHeaders(contentType = 'application/json') {
    const headers = {
        'X-CSRFToken': getCsrfToken()
    };
    
    const apiToken = getApiToken();
    if (apiToken) {
        headers['Authorization'] = `Bearer ${apiToken}`;
    }
    
    if (contentType) {
        headers['Content-Type'] = contentType;
    }
    
    return headers;
}

// Fonction pour effectuer une requête AJAX avec authentification
function ajaxRequest(url, method, data, successCallback, errorCallback) {
    // Déterminer le contentType en fonction du type de données
    let contentType = 'application/json';
    let processedData = data;
    
    // Si les données sont un FormData, ne pas spécifier de contentType
    if (data instanceof FormData) {
        contentType = null;
    } else if (method !== 'GET' && data && typeof data === 'object') {
        // Convertir les objets en JSON pour les requêtes non-GET
        processedData = JSON.stringify(data);
    }
    
    // Préparer les options de la requête
    const options = {
        url: url,
        type: method,
        headers: prepareAjaxHeaders(contentType),
        success: function(response) {
            if (successCallback) successCallback(response);
        },
        error: function(xhr, status, error) {
            console.error(`Erreur AJAX (${status}): ${error}`);
            
            // Vérifier si l'erreur est due à un token expiré
            if (xhr.status === 401) {
                // Supprimer le token et rediriger vers la page de connexion
                sessionStorage.removeItem('api_token');
                localStorage.removeItem('api_token');
                window.location.href = '/login/';
                return;
            }
            
            if (errorCallback) errorCallback(xhr, status, error);
        }
    };
    
    // Ajouter les données si nécessaire
    if (processedData) {
        if (data instanceof FormData) {
            options.data = processedData;
            options.processData = false;
            options.contentType = false;
        } else if (method === 'GET') {
            options.data = processedData;
        } else {
            options.data = processedData;
        }
    }
    
    // Effectuer la requête
    $.ajax(options);
}

// Fonction pour afficher une notification
function showNotification(type, message, duration = 3000) {
    const alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
    const icon = type === 'success' ? 'check-circle' : 'exclamation-triangle';
    
    // Créer la notification
    const notification = `
        <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
            <i class="fas fa-${icon} mr-2"></i>
            ${message}
            <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                <span aria-hidden="true">&times;</span>
            </button>
        </div>
    `;
    
    // Créer le conteneur s'il n'existe pas déjà
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }
    
    // Ajouter la notification au conteneur
    const notificationElement = document.createElement('div');
    notificationElement.innerHTML = notification;
    container.appendChild(notificationElement.firstChild);
    
    // Supprimer après la durée spécifiée
    setTimeout(() => {
        const alertElement = container.lastChild;
        if (alertElement) {
            alertElement.classList.remove('show');
            setTimeout(() => alertElement.remove(), 300);
        }
    }, duration);
}