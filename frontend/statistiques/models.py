# statistiques/models.py

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserRole(models.Model):
    """Modèle pour les rôles utilisateurs"""
    ROLE_CHOICES = (
        ('admin', 'Administrateur'),
        ('responsable', 'Responsable'),
        ('secretaire', 'Secrétaire'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='secretaire')
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

class CSVFile(models.Model):
    """Modèle pour les fichiers CSV téléchargés"""
    file = models.FileField(upload_to='csv_files/')
    name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)  # Rendre nullable
    uploaded_by_username = models.CharField(max_length=150, blank=True)  # Champ pour stocker le nom d'utilisateur
    uploaded_at = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return self.name

class Statistique(models.Model):
    """Modèle pour enregistrer les catégories de statistiques"""
    nom = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    chart_type = models.CharField(max_length=50)
    
    def __str__(self):
        return self.nom