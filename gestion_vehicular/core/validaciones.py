import smtplib
import socket
import time

import requests

_COEFICIENTES_CEDULA = (2, 1, 2, 1, 2, 1, 2, 1, 2)
_smtp_bloqueado_hasta = 0


def nombres_desde_correo(correo):
    """Obtiene nombre y apellido de un correo nombre.apellido@unl.edu.ec.

    Omite las iniciales de una sola letra, como en jorge.l.luzuriaga.
    """
    local = (correo or '').split('@')[0].strip().lower()
    partes = [parte for parte in local.split('.') if len(parte) > 1]
    if not partes:
        return '', ''
    nombres = partes[0].replace('_', ' ').title()
    apellidos = ' '.join(parte.replace('_', ' ').title() for parte in partes[1:])
    return nombres, apellidos


def validar_cedula(cedula):
    """Devuelve un mensaje de error, o None si la cédula ecuatoriana es válida."""
    cedula = (cedula or '').strip()
    if not cedula.isdigit() or len(cedula) != 10:
        return 'La cédula debe tener exactamente 10 números.'

    provincia = int(cedula[:2])
    if provincia < 1 or (provincia > 24 and provincia != 30):
        return 'La cédula no es válida.'
    if int(cedula[2]) > 5:
        return 'La cédula no es válida.'

    total = 0
    for indice, coeficiente in enumerate(_COEFICIENTES_CEDULA):
        valor = int(cedula[indice]) * coeficiente
        if valor > 9:
            valor -= 9
        total += valor
    verificador = (10 - (total % 10)) % 10
    if verificador != int(cedula[9]):
        return 'La cédula no es válida. Revisa los 10 números.'
    return None


def correo_institucional_existe(correo):
    """Consulta el servidor de correo de la UNL.

    True si la cuenta existe, False si el servidor responde que no existe,
    None si no se pudo comprobar (por ejemplo, si el hosting bloquea el puerto 25).
    """
    global _smtp_bloqueado_hasta
    if time.time() < _smtp_bloqueado_hasta:
        return None

    dominio = correo.split('@')[-1].strip().lower()
    try:
        respuesta = requests.get(
            'https://dns.google/resolve',
            params={'name': dominio, 'type': 'MX'},
            timeout=5,
        )
        respuesta.raise_for_status()
        registros = []
        for item in respuesta.json().get('Answer', []):
            if item.get('type') != 15:
                continue
            partes = str(item.get('data', '')).split()
            if len(partes) < 2:
                continue
            preferencia = int(partes[0]) if partes[0].isdigit() else 0
            registros.append((preferencia, partes[-1].rstrip('.')))
        registros.sort()
    except (requests.RequestException, ValueError, TypeError):
        return None

    if not registros:
        return None

    for _, host in registros[:2]:
        servidor = None
        try:
            servidor = smtplib.SMTP(timeout=6)
            servidor.connect(host, 25)
            servidor.ehlo('gestion-transporte.unl.edu.ec')
            servidor.mail('verificacion@unl.edu.ec')
            codigo, _mensaje = servidor.rcpt(correo)
            if 200 <= codigo < 300 or codigo == 552:
                return True
            if codigo in (550, 551, 553, 554):
                return False
        except (socket.timeout, socket.gaierror, TimeoutError, ConnectionError, OSError, smtplib.SMTPException):
            _smtp_bloqueado_hasta = time.time() + 600
            return None
        finally:
            if servidor is not None:
                try:
                    servidor.quit()
                except (OSError, smtplib.SMTPException):
                    pass
    return None
