from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth import views as auth_views
from .forms import UnlPasswordResetForm, UnlSetPasswordForm
from . import views

urlpatterns = [
    # AUTH
    path('', views.UnlLoginView.as_view(), name='login'),
    path('login/', views.UnlLoginView.as_view(), name='login_explicit'),
    path('logout/', views.custom_logout, name='logout'),
    path('dashboard-redirect/', views.dashboard_redirect, name='dashboard_redirect'),

    # REGISTRO DE USUARIO
    path('registrarse/', views.registrar_usuario, name='registrar_usuario'),
    path('registrarse/confirmar/', views.confirmar_codigo_registro, name='confirmar_codigo_registro'),
    path('registrarse/reenviar/', views.reenviar_codigo_registro, name='reenviar_codigo_registro'),
    path('registrarse/en-espera/', views.registro_en_espera, name='registro_en_espera'),
    path('verificar-correo/', views.verificar_correo_cuenta, name='verificar_correo_cuenta'),
    path('activar/<uidb64>/<token>/', views.activar_cuenta, name='activar_cuenta'),

    # PERFIL Y NOTIFICACIONES
    path('mi-perfil/', views.PerfilUsuarioView.as_view(), name='mi_perfil'),
    path('notificacion/<int:pk>/leer/', views.marcar_notificacion_leida, name='marcar_notificacion'),

    # DASHBOARDS
    path('portal-admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('portal-docente/home/', views.docente_home, name='docente_home'),
    path('portal-estudiante/home/', views.estudiante_home, name='estudiante_home'),
    path('portal-conductor/home/', views.conductor_home, name='conductor_home'),

    # DOCENTE
    path('home/', views.HomeView.as_view(), name='home'),
    path('solicitar/', views.SolicitarReservaView.as_view(), name='solicitar_reserva'),
    path('mis-reservas/', views.MisReservasListView.as_view(), name='lista_reservas'),
    path('mis-reservas/<int:pk>/detalle/', views.DocenteReservaDetailView.as_view(), name='docente_reserva_detalle'),
    path('mis-reservas/<int:pk>/cancelar/', views.CancelarReservaDocenteView.as_view(),
         name='cancelar_reserva_docente'),

    # CONDUCTOR
    path('conductor/viaje/<int:pk>/detalle/', views.ConductorReservaDetailView.as_view(),
         name='conductor_reserva_detalle'),
    path('conductor/viaje/<int:pk>/informe/', views.CrearInformeViajeView.as_view(), name='crear_informe_viaje'),

    # ADMIN - RESERVAS
    path('gestion/reservas/', views.AdminReservasListView.as_view(), name='admin_reservas'),
    path('gestion/reservas/<int:pk>/detalle/', views.AdminReservaDetailView.as_view(), name='admin_reserva_detalle'),
    path('gestion/reservas/<int:pk>/gestionar/', views.GestionarReservaView.as_view(), name='gestionar_reserva'),
    path('gestion/reservas/<int:pk>/eliminar/', views.EliminarReservaView.as_view(), name='eliminar_reserva'),

    # ADMIN - VEHICULOS
    path('gestion/vehiculos/', views.AdminVehiculosListView.as_view(), name='admin_vehiculos'),
    path('gestion/vehiculo/nuevo/', views.CrearVehiculoView.as_view(), name='crear_vehiculo'),
    path('gestion/vehiculo/<int:pk>/editar/', views.EditarVehiculoView.as_view(), name='editar_vehiculo'),
    path('gestion/vehiculo/<int:pk>/eliminar/', views.EliminarVehiculoView.as_view(), name='eliminar_vehiculo'),

    # ADMIN - USUARIOS
    path('gestion/usuarios/', views.AdminUsuariosListView.as_view(), name='admin_usuarios'),

    # RESET PASSWORD (USANDO FORMULARIO PERSONALIZADO)
    path('reset_password/', auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        form_class=UnlPasswordResetForm,
        email_template_name='registration/password_reset_email.html',         # Texto plano alternativo
        html_email_template_name='registration/password_reset_email.html',    # Formato HTML (Español)
        subject_template_name='registration/password_reset_subject.txt'       # Asunto personalizado
    ), name="password_reset"),

    path('reset_password_sent/', auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html"
    ), name="password_reset_done"),

    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html",
        form_class=UnlSetPasswordForm,
    ), name="password_reset_confirm"),

    path('reset_password_complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html"
    ), name="password_reset_complete"),
]