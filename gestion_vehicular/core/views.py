from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from .forms import UnlAuthenticationForm


# --- AUTENTICACIÓN (LOGIN) ---
class UnlLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = UnlAuthenticationForm
    redirect_authenticated_user = True

    def form_invalid(self, form):
        messages.error(self.request, "Credenciales incorrectas. Verifica tu correo y contraseña.")
        return super().form_invalid(form)


# --- CIERRE DE SESIÓN (LOGOUT) ---
def custom_logout(request):
    logout(request)
    messages.success(request, "Has cerrado sesión correctamente.")
    return redirect('login')


# --- REDIRECCIÓN TRAS INICIO DE SESIÓN EXITOSO ---
@login_required
def dashboard_redirect(request):
    return redirect('bienvenida')


# --- PÁGINA DE BIENVENIDA TRAS LOGIN (MÓDULO DE AUTENTICACIÓN) ---
@login_required
def bienvenida(request):
    user = request.user
    rol, perfil = user.get_rol_perfil()
    
    detalles = []
    if rol == 'Estudiante' and perfil:
        detalles.append(('Facultad', perfil.get_facultad_display()))
        detalles.append(('Carrera', perfil.get_carrera_display()))
        detalles.append(('Cédula', perfil.cedula))
    elif rol == 'Docente' and perfil:
        detalles.append(('Facultad', perfil.get_facultad_display()))
        detalles.append(('Título', perfil.titulo))
        detalles.append(('Cédula', perfil.cedula))
    elif rol == 'Conductor' and perfil:
        detalles.append(('Licencia', perfil.tipoLicencia))
        detalles.append(('Cédula', perfil.cedula))
    elif rol == 'Administrador' and perfil:
        detalles.append(('Cédula', perfil.cedula))
        detalles.append(('Fecha de Inicio', perfil.fechaInicio.strftime('%d/%m/%Y') if perfil.fechaInicio else '-'))

    context = {
        'user': user,
        'rol': rol,
        'nombre_completo': user.nombre_completo,
        'correo': user.correo,
        'detalles': detalles,
        'is_staff': user.is_staff,
    }
    return render(request, 'core/bienvenida.html', context)