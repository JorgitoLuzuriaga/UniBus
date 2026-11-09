import logging
import secrets
import time

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import TemplateView, CreateView, ListView, UpdateView, DetailView, DeleteView
from django.views import View
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import logout
from django.contrib import messages
from django.forms import modelform_factory
from django.db.models import Q
from django.shortcuts import render, redirect
from django.contrib.sites.shortcuts import get_current_site
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import Reserva, Vehiculo, EstadoReserva, Conductor, Asistencia, EstadoAsistencia, Cuenta, EstadoOperativo, \
    Notificacion, InformeViaje, IntentoRegistro
from .forms import (
    ReservaForm, VehiculoForm, GestionReservaForm, UnlAuthenticationForm, PerfilUsuarioForm,
    RegistroUnlForm, InformeViajeForm, CodigoRegistroForm,
)
from .correos import enviar_codigo_verificacion, notificar_registro_a_admins

User = get_user_model()
logger = logging.getLogger(__name__)
SOLICITUD_SESION = 'solicitud_registro'
CODIGO_CUENTA_SESION = 'codigo_cuenta'
CODIGO_MINUTOS = 15
MAX_INTENTOS_CODIGO = 5

# --- AUTENTICACIÓN ---
class UnlLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = UnlAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        if not self.request.POST.get('remember'):
            self.request.session.set_expiry(0)
        return super().form_valid(form)


@login_required
def dashboard_redirect(request):
    user = request.user

    es_admin = user.is_superuser or user.is_staff or hasattr(user, 'administrador_perfil')

    if not user.correo_verificado and not es_admin:
        return render(request, 'core/error_rol.html', {
            'titulo': 'Confirma tu correo',
            'mensaje': 'Esta cuenta todavía no demuestra que el correo institucional exista.',
            'detalle': 'Pide un código de 6 números y escríbelo aquí. Si no llega, revisa el spam o corrige el correo: puede que esa cuenta no exista.',
            'puede_verificar': True,
            'correo': user.correo,
        })

    if not es_admin and (not user.activo or user.rol_asignado == User.RolesDisponibles.NINGUNO):
        return render(request, 'core/error_rol.html', {
            'titulo': 'Solicitud en espera',
            'mensaje': 'Tu correo ya está confirmado. Falta que un administrador te asigne un rol.',
            'detalle': 'El administrador recibió el aviso. Cuando te asigne estudiante, docente o conductor desde el panel, podrás entrar a los módulos. Mientras tanto debes esperar.',
        })
    
    if hasattr(user, 'administrador_perfil'):
        return redirect('admin_dashboard')
    elif hasattr(user, 'docente_perfil'):
        return redirect('docente_home')
    elif hasattr(user, 'estudiante_perfil'):
        return redirect('estudiante_home')
    elif hasattr(user, 'conductor_perfil'):
        return redirect('conductor_home')
    elif user.is_superuser:
        return redirect('/admin/')
    else:
        return render(request, 'core/error_rol.html', {'mensaje': 'Usuario sin rol asignado.'})


def custom_logout(request):
    logout(request)
    return redirect('login')


# --- NOTIFICACIONES ---
@login_required
def marcar_notificacion_leida(request, pk):
    notificacion = get_object_or_404(Notificacion, pk=pk, destinatario=request.user)
    notificacion.leido = True
    notificacion.save()
    if notificacion.link: return redirect(notificacion.link)
    return redirect(request.META.get('HTTP_REFERER', '/'))

def _ip_cliente(request):
    reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if reenviada:
        return reenviada.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _mensaje_fallo_correo(exc):
    texto = str(exc).lower()
    if any(pista in texto for pista in (
        '550', '551', '553', 'user unknown', 'user not found', 'does not exist',
        'no such user', 'recipient address rejected', 'mailbox unavailable',
        'invalid recipient', 'recipient is invalid',
    )):
        return 'Esa cuenta de correo no existe. El mensaje no pudo entregarse; revisa el correo institucional.'
    if 'brevo_api_key' in texto or 'falta brevo_api_key' in texto:
        return 'No se envió el correo: en Render falta la variable BREVO_API_KEY.'
    if '401' in texto or 'unauthorized' in texto or 'unauthorised' in texto:
        return 'No se envió el correo: Brevo rechazó la clave API. Revisa BREVO_API_KEY en Render.'
    if 'sender' in texto or 'not yet activated' in texto:
        return 'No se envió el correo: el remitente no está verificado en Brevo. Confírmalo en Senders, domains & dedicated IPs.'
    return 'No se pudo enviar el código de verificación. Inténtalo de nuevo en unos minutos.'


def _nuevo_codigo():
    return f'{secrets.randbelow(1_000_000):06d}'


def _guardar_solicitud(request, datos, codigo):
    request.session[SOLICITUD_SESION] = {
        **datos,
        'codigo_hash': make_password(codigo),
        'expira': time.time() + CODIGO_MINUTOS * 60,
        'intentos': 0,
    }
    request.session.modified = True


def _crear_cuenta_confirmada(datos):
    user = User(
        correo=datos['correo'],
        nombres=datos['nombres'],
        apellidos=datos['apellidos'],
        cedula=datos['cedula'],
        facultad=datos['facultad'],
        carrera=datos['carrera'],
        tipo_licencia=datos.get('tipo_licencia') or '',
        correo_verificado=True,
        activo=False,
        rol_asignado=User.RolesDisponibles.NINGUNO,
    )
    user.password = datos['password']
    user.save()
    return user


def _bloqueo_de_registro(ip, correo):
    desde = timezone.now() - timedelta(hours=1)
    if ip and IntentoRegistro.objects.filter(ip=ip, creado__gte=desde).count() >= 20:
        return 'Superaste el número de intentos de registro permitidos desde esta red (20 por hora). Espera un momento e inténtalo de nuevo.'
    if correo and IntentoRegistro.objects.filter(correo__iexact=correo, creado__gte=desde).count() >= 5:
        return 'Este correo superó el número de intentos de registro permitidos (5 por hora).'
    return ''


def registrar_usuario(request):
    if request.method == 'POST':
        correo_intento = (request.POST.get('correo') or '').strip().lower()
        ip = _ip_cliente(request)
        mensaje_bloqueo = _bloqueo_de_registro(ip, correo_intento)
        IntentoRegistro.objects.filter(creado__lt=timezone.now() - timedelta(days=1)).delete()
        IntentoRegistro.objects.create(ip=ip or '0.0.0.0', correo=correo_intento[:254])
        form = RegistroUnlForm(request.POST)
        if mensaje_bloqueo:
            form.add_error(None, mensaje_bloqueo)
        elif form.is_valid():
            datos = form.datos_para_confirmar()
            codigo = _nuevo_codigo()
            try:
                enviar_codigo_verificacion(datos['correo'], datos['nombres'], codigo)
            except Exception as exc:
                logger.exception('No se envió el código a %s', datos['correo'])
                form.add_error('correo', _mensaje_fallo_correo(exc))
            else:
                _guardar_solicitud(request, datos, codigo)
                return redirect('confirmar_codigo_registro')
    else:
        form = RegistroUnlForm()
    return render(request, 'registration/registro.html', {'form': form})


def confirmar_codigo_registro(request):
    solicitud = request.session.get(SOLICITUD_SESION)
    if not solicitud:
        return redirect('registrar_usuario')

    form = CodigoRegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if time.time() > solicitud.get('expira', 0):
            form.add_error('codigo', 'El código venció. Pide uno nuevo.')
        elif solicitud.get('intentos', 0) >= MAX_INTENTOS_CODIGO:
            form.add_error('codigo', 'Superaste los intentos. Pide un código nuevo.')
        elif not check_password(form.cleaned_data['codigo'], solicitud.get('codigo_hash', '')):
            solicitud['intentos'] = solicitud.get('intentos', 0) + 1
            request.session[SOLICITUD_SESION] = solicitud
            request.session.modified = True
            restantes = MAX_INTENTOS_CODIGO - solicitud['intentos']
            form.add_error('codigo', f'El código no coincide. Te quedan {max(restantes, 0)} intentos.')
        elif User.objects.filter(correo__iexact=solicitud['correo']).exists():
            form.add_error('codigo', 'Este correo ya se registró. Inicia sesión.')
        else:
            try:
                with transaction.atomic():
                    user = _crear_cuenta_confirmada(solicitud)
            except IntegrityError:
                form.add_error('codigo', 'Ese correo o esa cédula ya están registrados.')
            else:
                request.session.pop(SOLICITUD_SESION, None)
                try:
                    notificar_registro_a_admins(user, request)
                except Exception:
                    logger.exception('La cuenta %s quedó creada, pero falló el aviso al administrador', user.pk)
                return redirect('registro_en_espera')

    return render(request, 'registration/confirmar_codigo.html', {
        'form': form,
        'correo': solicitud.get('correo', ''),
    })


def reenviar_codigo_registro(request):
    if request.method != 'POST':
        return redirect('confirmar_codigo_registro')
    solicitud = request.session.get(SOLICITUD_SESION)
    if not solicitud:
        return redirect('registrar_usuario')
    codigo = _nuevo_codigo()
    try:
        enviar_codigo_verificacion(solicitud['correo'], solicitud.get('nombres') or solicitud['correo'], codigo)
    except Exception as exc:
        logger.exception('No se reenvió el código a %s', solicitud.get('correo'))
        messages.error(request, _mensaje_fallo_correo(exc))
    else:
        solicitud['codigo_hash'] = make_password(codigo)
        solicitud['expira'] = time.time() + CODIGO_MINUTOS * 60
        solicitud['intentos'] = 0
        request.session[SOLICITUD_SESION] = solicitud
        request.session.modified = True
        messages.success(request, 'Enviamos un código nuevo. El anterior ya no sirve.')
    return redirect('confirmar_codigo_registro')


def registro_en_espera(request):
    return render(request, 'registration/registro_pendiente.html')


@login_required
def verificar_correo_cuenta(request):
    user = request.user
    if user.correo_verificado:
        return redirect('dashboard_redirect')
    if request.method != 'POST':
        return redirect('dashboard_redirect')

    accion = request.POST.get('accion')
    if accion == 'enviar':
        codigo = _nuevo_codigo()
        try:
            enviar_codigo_verificacion(user.correo, user.nombres or user.correo, codigo)
        except Exception as exc:
            logger.exception('No se envió el código de la cuenta %s', user.pk)
            messages.error(request, _mensaje_fallo_correo(exc))
        else:
            request.session[CODIGO_CUENTA_SESION] = {
                'uid': user.pk,
                'hash': make_password(codigo),
                'expira': time.time() + CODIGO_MINUTOS * 60,
                'intentos': 0,
            }
            messages.success(request, f'Enviamos un código a {user.correo}.')
    elif accion == 'confirmar':
        datos = request.session.get(CODIGO_CUENTA_SESION) or {}
        codigo = (request.POST.get('codigo') or '').strip()
        if datos.get('uid') != user.pk:
            messages.error(request, 'Primero pide el código.')
        elif time.time() > datos.get('expira', 0) or datos.get('intentos', 0) >= MAX_INTENTOS_CODIGO:
            messages.error(request, 'Ese código venció o agotó los intentos. Pide otro.')
        elif not codigo.isdigit() or not check_password(codigo, datos.get('hash', '')):
            datos['intentos'] = datos.get('intentos', 0) + 1
            request.session[CODIGO_CUENTA_SESION] = datos
            request.session.modified = True
            messages.error(request, 'El código no coincide.')
        else:
            user.correo_verificado = True
            user.save(update_fields=['correo_verificado'])
            request.session.pop(CODIGO_CUENTA_SESION, None)
            try:
                notificar_registro_a_admins(user, request)
            except Exception:
                logger.exception('No se avisó al administrador de la cuenta %s', user.pk)
            messages.success(request, 'Correo confirmado. Ahora debes esperar a que un administrador te asigne el rol.')
    return redirect('dashboard_redirect')

def activar_cuenta(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.correo_verificado = True
        user.save(update_fields=['correo_verificado'])
        return render(request, 'registration/activacion_exitosa.html')
    return render(request, 'registration/activacion_fallida.html')

# --- PERFIL DE USUARIO ---
class PerfilUsuarioView(LoginRequiredMixin, UpdateView):
    template_name = 'core/perfil_form.html'
    success_url = reverse_lazy('mi_perfil')

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        tiene_perfil = any(
            hasattr(user, perfil)
            for perfil in ('administrador_perfil', 'docente_perfil', 'conductor_perfil', 'estudiante_perfil')
        )
        if not tiene_perfil:
            messages.info(request, 'Tu perfil estará disponible cuando un administrador te asigne un rol.')
            return redirect('dashboard_redirect')
        return super().dispatch(request, *args, **kwargs)

    def get_object(self):
        u = self.request.user
        if hasattr(u, 'administrador_perfil'): return u.administrador_perfil
        if hasattr(u, 'docente_perfil'): return u.docente_perfil
        if hasattr(u, 'conductor_perfil'): return u.conductor_perfil
        if hasattr(u, 'estudiante_perfil'): return u.estudiante_perfil
        return None

    def get_form_class(self):
        obj = self.get_object()
        if not obj: return None
        campos = ['nombres', 'apellidos', 'cedula']
        if hasattr(obj, 'tipoLicencia'): campos.append('tipoLicencia')
        return modelform_factory(type(obj), form=PerfilUsuarioForm, fields=campos)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['rol_usuario'] = self.request.user.rol_nombre
        ctx['email_usuario'] = self.request.user.correo
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Perfil actualizado correctamente.")
        return super().form_valid(form)


# --- DOCENTE ---
@login_required
def docente_home(request):
    if not hasattr(request.user, 'docente_perfil'): return redirect('login')
    context = {'user_name': request.user.docente_perfil.getNombreCompleto(),
               'facultad': request.user.docente_perfil.get_facultad_display()}
    return render(request, 'core/docente_home.html', context)


class SolicitarReservaView(LoginRequiredMixin, CreateView):
    model = Reserva
    form_class = ReservaForm
    template_name = 'core/solicitud_form.html'
    success_url = reverse_lazy('docente_home')

    def form_valid(self, form):
        if hasattr(self.request.user, 'docente_perfil'):
            form.instance.solicitante = self.request.user.docente_perfil

        # VALIDACIÓN DE CHOQUE DE HORARIOS
        inicio = form.cleaned_data['fechaInicio']
        fin = form.cleaned_data['fechaFin']
        aforo = form.cleaned_data['aforo']

        ocupados = Reserva.objects.filter(
            Q(estado='ACEPTADA') | Q(estado='ESPERA_CONDUCTOR'),
            fechaInicio__lt=fin,
            fechaFin__gt=inicio
        ).values_list('vehiculo_id', flat=True)

        vehiculo_optimo = Vehiculo.objects.filter(
            disponibilidad=True, estado='ACTIVO', aforo__gte=aforo
        ).exclude(id__in=ocupados).first()

        if vehiculo_optimo:
            form.instance.vehiculo = vehiculo_optimo
            if vehiculo_optimo.conductor:
                form.instance.conductor = vehiculo_optimo.conductor
                form.instance.estado = EstadoReserva.ESPERA_CONDUCTOR
                messages.success(self.request, f"Vehículo asignado: {vehiculo_optimo.placa}.")
            else:
                form.instance.estado = EstadoReserva.ESPERA_ADMIN
                messages.warning(self.request, "Vehículo sin conductor asignado. Pendiente de Admin.")
        else:
            form.instance.estado = EstadoReserva.ESPERA_ADMIN
            messages.warning(self.request, "Sin vehículo disponible en ese horario. Enviado a lista de espera.")

        response = super().form_valid(form)

        estudiantes = form.cleaned_data.get('estudiantes_seleccion')
        if estudiantes:
            for est in estudiantes:
                Asistencia.objects.create(reserva=self.object, estudiante=est, estado=EstadoAsistencia.SIN_RESPUESTA)
        return response


class MisReservasListView(LoginRequiredMixin, ListView):
    model = Reserva
    template_name = 'core/lista_reservas.html'
    context_object_name = 'reservas'

    def get_queryset(self):
        if hasattr(self.request.user, 'docente_perfil'):
            return Reserva.objects.filter(solicitante=self.request.user.docente_perfil).order_by('-fechaInicio')
        return Reserva.objects.none()


class DocenteReservaDetailView(LoginRequiredMixin, DetailView):
    model = Reserva
    template_name = 'core/docente_reserva_detail.html'
    context_object_name = 'reserva'

    def get_queryset(self):
        if hasattr(self.request.user, 'docente_perfil'): return Reserva.objects.filter(
            solicitante=self.request.user.docente_perfil)
        return Reserva.objects.none()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['confirmados_count'] = self.object.asistencias.filter(estado=EstadoAsistencia.CONFIRMADO).count()
        ctx['total_estudiantes'] = self.object.asistencias.count()
        return ctx


class CancelarReservaDocenteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        reserva = get_object_or_404(Reserva, pk=pk, solicitante=request.user.docente_perfil)
        estados_permitidos = [EstadoReserva.ESPERA_ADMIN, EstadoReserva.ESPERA_CONDUCTOR]

        if reserva.estado in estados_permitidos:
            reserva.estado = EstadoReserva.ANULADA
            reserva.save()
            messages.success(request, "Has anulado la solicitud de reserva correctamente.")
        else:
            messages.error(request, "No puedes anular esta reserva porque ya fue procesada o finalizada.")

        return redirect('lista_reservas')


# --- CONDUCTOR ---
@login_required
def conductor_home(request):
    if not hasattr(request.user, 'conductor_perfil'): return redirect('login')
    conductor = request.user.conductor_perfil

    if request.method == 'POST':
        reserva_id = request.POST.get('reserva_id')
        accion = request.POST.get('accion')
        try:
            reserva = Reserva.objects.get(id=reserva_id, conductor=conductor)
            if accion == 'aceptar':
                reserva.estado = EstadoReserva.ACEPTADA
                reserva.save()
                messages.success(request, "Viaje aceptado.")
            elif accion == 'rechazar':
                reserva.estado = EstadoReserva.CHOFER_RECHAZO
                reserva.save()
                messages.info(request, "Viaje rechazado.")
        except Reserva.DoesNotExist:
            pass

    ctx = {
        'user_name': conductor.getNombreCompleto(),
        'pendientes': Reserva.objects.filter(conductor=conductor, estado=EstadoReserva.ESPERA_CONDUCTOR),
        'confirmados': Reserva.objects.filter(conductor=conductor).filter(
            Q(estado=EstadoReserva.ACEPTADA) | Q(estado=EstadoReserva.FINALIZADA))
    }
    return render(request, 'core/conductor_home.html', ctx)


class ConductorReservaDetailView(LoginRequiredMixin, DetailView):
    model = Reserva
    template_name = 'core/conductor_reserva_detail.html'
    context_object_name = 'reserva'

    def get_queryset(self):
        if hasattr(self.request.user, 'conductor_perfil'): return Reserva.objects.filter(
            conductor=self.request.user.conductor_perfil)
        return Reserva.objects.none()


class CrearInformeViajeView(LoginRequiredMixin, CreateView):
    model = InformeViaje
    form_class = InformeViajeForm
    template_name = 'core/informe_viaje_form.html'
    success_url = reverse_lazy('conductor_home')

    def form_valid(self, form):
        reserva = get_object_or_404(Reserva, pk=self.kwargs['pk'])
        form.instance.reserva = reserva
        response = super().form_valid(form)

        reserva.estado = EstadoReserva.FINALIZADA
        reserva.save()
        messages.success(self.request, "Informe enviado y viaje finalizado.")
        return response


# --- ADMIN ---
@login_required
def admin_dashboard(request):
    if not hasattr(request.user, 'administrador_perfil') and not request.user.is_superuser: return redirect('login')
    nombre = request.user.administrador_perfil.getNombreCompleto() if hasattr(request.user,
                                                                              'administrador_perfil') else 'SuperAdmin'
    context = {
        'user_name': nombre,
        'vehiculos_activos': Vehiculo.objects.filter(estado=EstadoOperativo.ACTIVO).count(),
        'reservas_pendientes': Reserva.objects.filter(estado=EstadoReserva.ESPERA_ADMIN).count(),
        'usuarios_totales': Cuenta.objects.count()
    }
    return render(request, 'core/admin_dashboard.html', context)


class AdminReservasListView(LoginRequiredMixin, ListView):
    model = Reserva
    template_name = 'core/admin_reservas_list.html'
    context_object_name = 'reservas'

    def get_queryset(self): return Reserva.objects.exclude(estado=EstadoReserva.ANULADA).order_by('-fechaInicio')


class AdminReservaDetailView(LoginRequiredMixin, DetailView):
    model = Reserva
    template_name = 'core/admin_reserva_detail.html'
    context_object_name = 'reserva'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['informe'] = self.object.informe
        except InformeViaje.DoesNotExist:
            context['informe'] = None
        return context


class GestionarReservaView(LoginRequiredMixin, UpdateView):
    model = Reserva
    form_class = GestionReservaForm
    template_name = 'core/gestion_reserva_form.html'
    success_url = reverse_lazy('admin_reservas')

    def form_valid(self, form):
        messages.success(self.request, "Reserva actualizada.")
        return super().form_valid(form)


class EliminarReservaView(LoginRequiredMixin, DeleteView):
    model = Reserva
    template_name = 'core/reserva_confirm_delete.html'
    success_url = reverse_lazy('admin_reservas')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Reserva eliminada.")
        return super().delete(request, *args, **kwargs)


class AdminVehiculosListView(LoginRequiredMixin, ListView):
    model = Vehiculo
    template_name = 'core/admin_vehiculos_list.html'
    context_object_name = 'vehiculos'


class CrearVehiculoView(LoginRequiredMixin, CreateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'core/vehiculo_form.html'
    success_url = reverse_lazy('admin_vehiculos')

    def form_valid(self, form):
        messages.success(self.request, "Vehículo registrado.")
        return super().form_valid(form)


class EditarVehiculoView(LoginRequiredMixin, UpdateView):
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'core/vehiculo_form.html'
    success_url = reverse_lazy('admin_vehiculos')

    def form_valid(self, form):
        messages.success(self.request, "Vehículo actualizado.")
        return super().form_valid(form)


class EliminarVehiculoView(LoginRequiredMixin, DeleteView):
    model = Vehiculo
    template_name = 'core/vehiculo_confirm_delete.html'
    success_url = reverse_lazy('admin_vehiculos')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Vehículo eliminado.")
        return super().delete(request, *args, **kwargs)


class AdminUsuariosListView(LoginRequiredMixin, ListView):
    model = Cuenta
    template_name = 'core/admin_usuarios_list.html'
    context_object_name = 'usuarios'

    def get_queryset(self): return Cuenta.objects.all().order_by('-date_joined')


# --- ESTUDIANTE ---
@login_required
def estudiante_home(request):
    if not hasattr(request.user, 'estudiante_perfil'): return redirect('login')
    estudiante = request.user.estudiante_perfil
    if request.method == 'POST':
        asistencia_id = request.POST.get('asistencia_id')
        accion = request.POST.get('accion')
        try:
            asistencia = Asistencia.objects.get(id=asistencia_id, estudiante=estudiante)
            if accion == 'confirmar':
                asistencia.estado = EstadoAsistencia.CONFIRMADO;
                asistencia.save()
                messages.success(request, f"Asistencia confirmada.")
            elif accion == 'rechazar':
                asistencia.estado = EstadoAsistencia.RECHAZADO;
                asistencia.save()
                messages.warning(request, f"Viaje rechazado.")
        except Asistencia.DoesNotExist:
            pass
    mis_viajes = Asistencia.objects.filter(estudiante=estudiante).filter(
        Q(reserva__estado='ACEPTADA') | Q(reserva__estado='FINALIZADA')).order_by('-reserva__fechaInicio')
    return render(request, 'core/estudiante_home.html',
                  {'user_name': estudiante.getNombreCompleto(), 'mis_viajes': mis_viajes})


class HomeView(TemplateView): template_name = 'core/home.html'