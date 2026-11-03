from django.urls import path
from django.contrib.auth import views as auth_views
from .forms import UnlPasswordResetForm
from . import views

urlpatterns = [
    # AUTENTICACIÓN (LOGIN & LOGOUT)
    path('', views.UnlLoginView.as_view(), name='login'),
    path('login/', views.UnlLoginView.as_view(), name='login_explicit'),
    path('logout/', views.custom_logout, name='logout'),
    path('dashboard-redirect/', views.dashboard_redirect, name='dashboard_redirect'),

    # PÁGINA TRAS INICIAR SESIÓN (DEMOSTRACIÓN DE LOGIN Y ROLES)
    path('bienvenida/', views.bienvenida, name='bienvenida'),

    # RECUPERACIÓN DE CONTRASEÑA
    path('reset_password/', auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        form_class=UnlPasswordResetForm
    ), name="password_reset"),

    path('reset_password_sent/', auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"
    ), name="password_reset_done"),

    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html"
    ), name="password_reset_confirm"),

    path('reset_password_complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html"
    ), name="password_reset_complete"),
]