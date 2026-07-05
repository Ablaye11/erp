from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.is_ajax() if hasattr(request, 'is_ajax') else request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Handled if we want to login via AJAX, but standard is fine
        pass

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            from axes.exceptions import AxesBackendPermissionDenied
            try:
                user = authenticate(request=request, username=username, password=password)
                if user is not None:
                    login(request, user)
                    # Reset any impersonated role upon fresh login
                    if 'active_role' in request.session:
                        del request.session['active_role']
                    return redirect('dashboard')
                else:
                    messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
            except AxesBackendPermissionDenied:
                messages.error(request, "Trop de tentatives de connexion. Votre compte ou adresse IP est temporairement bloqué(e). Veuillez réessayer dans une heure.")
        else:
            messages.error(request, "Identifiants invalides.")
    else:
        form = AuthenticationForm()
        
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, "Vous avez été déconnecté avec succès.")
    return redirect('login')
