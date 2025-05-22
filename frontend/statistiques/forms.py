# statistiques/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import CSVFile, UserRole

class CSVUploadForm(forms.ModelForm):
    """Formulaire pour uploader un fichier CSV"""
    class Meta:
        model = CSVFile
        fields = ['file', 'name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'file': forms.FileInput(attrs={'class': 'form-control-file'})
        }
        
    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            if not file.name.endswith('.csv'):
                raise forms.ValidationError("Le fichier doit être au format CSV.")
            if file.size > 16 * 1024 * 1024:  # 16MB
                raise forms.ValidationError("Le fichier ne doit pas dépasser 16MB.")
        return file

class UserRegisterForm(UserCreationForm):
    """Formulaire pour l'inscription des utilisateurs"""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'votre.email@example.com'
        })
    )
    
    ROLE_CHOICES = (
        ('admin', 'Administrateur'),
        ('responsable_recherche', 'Responsable Recherche'),
        ('responsable_admin', 'Responsable Administratif'),
        ('secretaire', 'Secrétaire'),
    )
    
    role = forms.ChoiceField(
        choices=ROLE_CHOICES, 
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2', 'role']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom d\'utilisateur'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ajouter les classes Bootstrap aux champs de mot de passe
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Mot de passe'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirmer le mot de passe'
        })
        
        # Personnaliser les labels
        self.fields['username'].label = 'Nom d\'utilisateur'
        self.fields['email'].label = 'Adresse email'
        self.fields['role'].label = 'Rôle'
        self.fields['password1'].label = 'Mot de passe'
        self.fields['password2'].label = 'Confirmer le mot de passe'
        
        # Aide contextuelle
        self.fields['username'].help_text = 'Uniquement lettres, chiffres et @/./+/-/_ autorisés.'
        self.fields['password1'].help_text = 'Minimum 8 caractères, pas uniquement numérique.'
        self.fields['password2'].help_text = 'Saisissez le même mot de passe que précédemment.'
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un utilisateur avec cette adresse email existe déjà.")
        return email

class DataUpdateForm(forms.Form):
    """Formulaire pour mettre à jour des données"""
    annee = forms.IntegerField(
        label="Année",
        min_value=2000,
        max_value=2050,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '2024'
        })
    )
    
    nombre_fie1 = forms.IntegerField(
        label="Nombre FIE1",
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '120'
        })
    )
    
    nombre_fie2 = forms.IntegerField(
        label="Nombre FIE2",
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '100'
        })
    )
    
    nombre_fie3 = forms.IntegerField(
        label="Nombre FIE3",
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '90'
        })
    )
    
    taux_boursiers = forms.FloatField(
        label="Taux de boursiers",
        min_value=0,
        max_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '0.25',
            'step': '0.01'
        }),
        help_text="Valeur entre 0 et 1 (ex: 0.25 pour 25%)"
    )
    
    nombre_diplomes = forms.IntegerField(
        label="Nombre de diplômés",
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '85'
        })
    )
    
    nombre_handicapes = forms.IntegerField(
        label="Nombre d'étudiants handicapés",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '10'
        })
    )
    
    nombre_etrangers = forms.IntegerField(
        label="Nombre d'étudiants étrangers",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '15'
        })
    )
    
    nombre_demissionnes = forms.IntegerField(
        label="Nombre d'étudiants démissionnés",
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '5'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        annee = cleaned_data.get('annee')
        
        # Validation personnalisée si nécessaire
        if annee and annee > 2025:
            self.add_error('annee', 'L\'année ne peut pas être dans le futur.')
        
        return cleaned_data