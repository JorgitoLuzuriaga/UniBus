from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms
from .models import (
    Cuenta,
    Administrador,
    Docente,
    Estudiante,
    Vehiculo,
    Reserva,
    Conductor,
    Universidad,
)
from .models import Facultad, Carrera


# --- FORMULARIO PERSONALIZADO ---
class CuentaCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Cuenta
        fields = ('correo', 'password')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


# --- CONFIGURACIÓN CUENTA ---
@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = ('correo', 'nombres', 'apellidos', 'facultad', 'carrera', 'rol_asignado', 'correo_verificado', 'activo')
    list_filter = ('rol_asignado', 'activo', 'correo_verificado', 'facultad')
    fields = (
        'correo', 'nombres', 'apellidos', 'cedula', 'facultad', 'carrera',
        'tipo_licencia', 'correo_verificado', 'rol_asignado', 'activo', 'is_staff', 'is_superuser',
    )

    def save_model(self, request, obj, form, change):
        roles_operativos = {
            Cuenta.RolesDisponibles.ESTUDIANTE,
            Cuenta.RolesDisponibles.DOCENTE,
            Cuenta.RolesDisponibles.CONDUCTOR,
        }
        if obj.rol_asignado in roles_operativos:
            obj.activo = True
        elif obj.rol_asignado == Cuenta.RolesDisponibles.NINGUNO and not obj.is_superuser and not obj.is_staff:
            obj.activo = False

        super().save_model(request, obj, form, change)

        if obj.rol_asignado in roles_operativos and not (obj.nombres and obj.apellidos and obj.cedula):
            obj.activo = False
            obj.rol_asignado = Cuenta.RolesDisponibles.NINGUNO
            obj.save(update_fields=['activo', 'rol_asignado'])
            messages.error(request, 'No se asignó el rol: la cuenta necesita nombres, apellidos y cédula.')
            return

        if obj.activo:
            facultad_seleccionada = obj.facultad or Facultad.FEIRNNR
            carrera_seleccionada = obj.carrera or Carrera.COMPUTACION
            licencia_ingresada = (obj.tipo_licencia or '').upper().replace('TIPO', '').strip() or 'C'

            # --- CASO 1: SE ASIGNÓ ROL ESTUDIANTE ---
            if obj.rol_asignado == Cuenta.RolesDisponibles.ESTUDIANTE:
                # 1. Eliminamos perfiles de otros roles si existían previamente
                if hasattr(obj, 'docente_perfil'):
                    obj.docente_perfil.delete()
                if hasattr(obj, 'conductor_perfil'):
                    obj.conductor_perfil.delete()
                
                # 2. Creamos el perfil de estudiante si no lo tiene
                if not hasattr(obj, 'estudiante_perfil'):
                    Estudiante.objects.create(
                        cuenta=obj, nombres=obj.nombres, apellidos=obj.apellidos,
                        cedula=obj.cedula, facultad=facultad_seleccionada, carrera=carrera_seleccionada
                    )

            # --- CASO 2: SE ASIGNÓ ROL DOCENTE ---
            elif obj.rol_asignado == Cuenta.RolesDisponibles.DOCENTE:
                # 1. Limpieza de perfiles viejos
                if hasattr(obj, 'estudiante_perfil'):
                    obj.estudiante_perfil.delete()
                if hasattr(obj, 'conductor_perfil'):
                    obj.conductor_perfil.delete()
                
                # 2. Creamos el perfil docente
                if not hasattr(obj, 'docente_perfil'):
                    Docente.objects.create(
                        cuenta=obj, nombres=obj.nombres, apellidos=obj.apellidos,
                        cedula=obj.cedula, facultad=facultad_seleccionada, titulo='Docente UNL'
                    )

            # --- CASO 3: SE ASIGNÓ ROL CONDUCTOR ---
            elif obj.rol_asignado == Cuenta.RolesDisponibles.CONDUCTOR:
                # 1. Limpieza de perfiles viejos
                if hasattr(obj, 'estudiante_perfil'):
                    obj.estudiante_perfil.delete()
                if hasattr(obj, 'docente_perfil'):
                    obj.docente_perfil.delete()
                
                # 2. Creamos el perfil conductor
                if not hasattr(obj, 'conductor_perfil'):
                    Conductor.objects.create(
                        cuenta=obj, nombres=obj.nombres, apellidos=obj.apellidos,
                        cedula=obj.cedula, tipoLicencia=licencia_ingresada, disponibilidad=True
                    )
            
            # --- CASO 4: SE REGRESÓ A PENDIENTE (NINGUNO) ---
            elif obj.rol_asignado == Cuenta.RolesDisponibles.NINGUNO:
                # Si el administrador decide retirar los roles, limpiamos todas las tablas
                if hasattr(obj, 'estudiante_perfil'): obj.estudiante_perfil.delete()
                if hasattr(obj, 'docente_perfil'): obj.docente_perfil.delete()
                if hasattr(obj, 'conductor_perfil'): obj.conductor_perfil.delete()



# --- REGISTRO DE MODELOS ---
#admin.site.register(Cuenta, CuentaAdmin)
admin.site.register(Administrador)
admin.site.register(Docente)
admin.site.register(Estudiante)

# --- LOS QUE FALTABAN ---
admin.site.register(Conductor)  # <--- Agregado
admin.site.register(Universidad)  # <--- Agregado

admin.site.register(Vehiculo)
admin.site.register(Reserva)