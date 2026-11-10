from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Reserva, Notificacion, EstadoReserva, Cuenta, Asistencia


@receiver(pre_save, sender=Reserva)
def guardar_estado_anterior(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._estado_anterior = Reserva.objects.get(pk=instance.pk).estado
        except Reserva.DoesNotExist:
            instance._estado_anterior = None
    else:
        instance._estado_anterior = None


@receiver(post_save, sender=Reserva)
def gestionar_flujo_reserva(sender, instance, created, **kwargs):
    # 1. CREADA -> AVISA ADMIN
    if created:
        admins = Cuenta.objects.filter(is_superuser=True) | Cuenta.objects.filter(administrador_perfil__isnull=False)
        for admin in admins:
            Notificacion.objects.create(
                destinatario=admin,
                mensaje=f"Nueva solicitud de {instance.solicitante.getNombreCompleto()}: {instance.motivo}",
                link="/gestion/reservas/"
            )

    if hasattr(instance, '_estado_anterior') and instance._estado_anterior != instance.estado:

        # 2. ESPERA_CONDUCTOR -> AVISA CHOFER
        if instance.estado == EstadoReserva.ESPERA_CONDUCTOR and instance.conductor:
            Notificacion.objects.create(
                destinatario=instance.conductor.cuenta,
                mensaje=f"Asignación de viaje a {instance.destino_canton}. Por favor confirma.",
                link="/portal-conductor/home/"
            )

        # 3. ACEPTADA -> AVISA A TODOS (Y RECORDATORIO DE INFORME AL CHOFER)
        elif instance.estado == EstadoReserva.ACEPTADA:
            # A. Admin
            admins = Cuenta.objects.filter(is_superuser=True) | Cuenta.objects.filter(
                administrador_perfil__isnull=False)
            for admin in admins:
                Notificacion.objects.create(
                    destinatario=admin,
                    mensaje=f"Viaje a {instance.destino_canton} CONFIRMADO por el conductor.",
                    link="/gestion/reservas/"
                )

            # B. Docente
            Notificacion.objects.create(
                destinatario=instance.solicitante.cuenta,
                mensaje=f"Tu solicitud a {instance.destino_canton} ha sido APROBADA.",
                link="/mis-reservas/"
            )

            # C. Estudiantes
            for asistencia in instance.asistencias.all():
                Notificacion.objects.create(
                    destinatario=asistencia.estudiante.cuenta,
                    mensaje=f"Viaje confirmado a {instance.destino_canton}. Confirma tu asistencia.",
                    link="/portal-estudiante/home/"
                )

            if instance.conductor_id:
                Notificacion.objects.create(
                    destinatario=instance.conductor.cuenta,
                    mensaje="Recuerda llenar el INFORME DE VIAJE al finalizar la ruta.",
                    link=f"/conductor/viaje/{instance.id}/informe/"
                )

        # 4. FINALIZADA -> AVISA ADMIN
        elif instance.estado == EstadoReserva.FINALIZADA:
            admins = Cuenta.objects.filter(is_superuser=True) | Cuenta.objects.filter(
                administrador_perfil__isnull=False)
            for admin in admins:
                Notificacion.objects.create(
                    destinatario=admin,
                    mensaje=f"Viaje a {instance.destino_canton} FINALIZADO. Informe entregado.",
                    link=f"/gestion/reservas/{instance.id}/gestionar/"
                )

        # 5. RECHAZADA -> AVISA DOCENTE
        elif instance.estado == EstadoReserva.RECHAZADA:
            Notificacion.objects.create(
                destinatario=instance.solicitante.cuenta,
                mensaje=f"Tu solicitud a {instance.destino_canton} ha sido RECHAZADA.",
                link="/mis-reservas/"
            )

        # 6. CHOFER RECHAZA -> AVISA ADMIN
        elif instance.estado == EstadoReserva.CHOFER_RECHAZO:
            admins = Cuenta.objects.filter(is_superuser=True) | Cuenta.objects.filter(
                administrador_perfil__isnull=False)
            for admin in admins:
                Notificacion.objects.create(
                    destinatario=admin,
                    mensaje=f"ALERTA: Chofer rechazó viaje a {instance.destino_canton}. Reasignar.",
                    link=f"/gestion/reservas/{instance.id}/gestionar/"
                )