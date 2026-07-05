from django import forms
from django.contrib.auth import get_user_model
from accounts.models import SchoolClass

User = get_user_model()

class StudentCreationForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True, label="Prénom")
    last_name = forms.CharField(max_length=150, required=True, label="Nom")
    username = forms.CharField(max_length=150, required=True, label="Nom d'utilisateur")
    email = forms.EmailField(required=True, label="Email")
    class_id = forms.IntegerField(required=True, label="ID de la classe")
    parent_phone = forms.CharField(max_length=20, required=False, label="Téléphone parent")

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà utilisé.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email

    def clean_class_id(self):
        class_id = self.cleaned_data.get('class_id')
        if not SchoolClass.objects.filter(id=class_id).exists():
            raise forms.ValidationError("La classe sélectionnée n'existe pas.")
        return class_id


class TeacherCreationForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True, label="Prénom")
    last_name = forms.CharField(max_length=150, required=True, label="Nom")
    username = forms.CharField(max_length=150, required=True, label="Nom d'utilisateur")
    email = forms.EmailField(required=True, label="Email")

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ce nom d'utilisateur est déjà utilisé.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée.")
        return email


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'avatar']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # S'assurer que l'email n'est pas utilisé par un autre utilisateur
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Cette adresse e-mail est déjà utilisée par un autre compte.")
        return email
