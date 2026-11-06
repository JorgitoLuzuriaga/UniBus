from .models import Notificacion

def notificaciones_globales(request):
    if request.user.is_authenticated:
        # Obtenemos las no leídas
        mis_notificaciones = Notificacion.objects.filter(destinatario=request.user, leido=False).order_by('-fecha_creacion')
        return {
            'notificaciones_no_leidas': mis_notificaciones,
            'conteo_notificaciones': mis_notificaciones.count()
        }
    return {}