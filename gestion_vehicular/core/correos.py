import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from anymail.message import AnymailMessage
from decouple import config

from .models import Cuenta, Notificacion

logger = logging.getLogger(__name__)


def _enviar(asunto, cuerpo_html, destinatarios):
    mensaje = AnymailMessage(
        subject=asunto,
        body='Abre este mensaje en un correo que pueda mostrar HTML.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=destinatarios,
    )
    mensaje.attach_alternative(cuerpo_html, 'text/html')
    mensaje.send()


def enviar_confirmacion_registro(user, request):
    protocolo = 'https' if request.is_secure() else 'http'
    contexto = {
        'user': user,
        'domain': request.get_host(),
        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
        'protocol': protocolo,
    }
    html = render_to_string('registration/activacion_email.html', contexto)
    _enviar('Confirma tu correo - Gestión de Transporte UNL', html, [user.correo])


def notificar_registro_a_admins(user, request):
    admins = Cuenta.objects.filter(
        Q(is_staff=True) | Q(administrador_perfil__isnull=False)
    ).distinct()
    correos = {admin.correo for admin in admins if admin.correo}
    extra = config('ADMIN_EMAIL', default='').strip()
    if extra:
        correos.add(extra)
    if not correos:
        correos.add('jorge.luzuriaga@unl.edu.ec')
    correos.discard(user.correo)

    enlace = request.build_absolute_uri(
        reverse('admin:core_cuenta_change', args=[user.pk])
    )
    contexto = {
        'user': user,
        'enlace': enlace,
        'facultad': user.get_facultad_display() or 'No indicada',
        'carrera': user.get_carrera_display() or 'No indicada',
        'licencia': f'Tipo {user.tipo_licencia}' if user.tipo_licencia else 'No aplica',
    }
    if correos:
        html = render_to_string('registration/admin_nuevo_registro_email.html', contexto)
        try:
            _enviar(
                f'Nuevo registro pendiente: {user.nombre_completo}',
                html,
                sorted(correos),
            )
        except Exception:
            logger.exception('No se pudo avisar por correo del registro %s', user.pk)

    for admin in admins:
        Notificacion.objects.create(
            destinatario=admin,
            mensaje=f'Nuevo registro de {user.nombre_completo} ({user.correo}). Asigna el rol.',
            link=reverse('admin:core_cuenta_change', args=[user.pk]),
        )
