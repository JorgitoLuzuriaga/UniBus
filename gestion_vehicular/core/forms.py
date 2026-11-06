from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.core.exceptions import ValidationError
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from django.contrib.auth.forms import AuthenticationForm
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from .models import Conductor, Facultad, Reserva, Vehiculo, Docente, Estudiante, Carrera, Cuenta, InformeViaje


# --- LOGIN PERSONALIZADO ---
class UnlAuthenticationForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'usuario@unl.edu.ec',
        'autofocus': True
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Contraseña',
    }))
    captcha = ReCaptchaField(
    label='',
    widget=ReCaptchaV2Checkbox(api_params={'hl': 'es'}),
    error_messages={'required': 'Confirma que no eres un robot.'},
)

    def clean_username(self):
        correo = self.cleaned_data.get('username')
        if correo and not correo.endswith('@unl.edu.ec'):
            raise ValidationError("Acceso restringido: Solo se permiten correos institucionales (@unl.edu.ec).")
        return correo


# --- RECUPERACIÓN DE CONTRASEÑA ---
class UnlPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        """Buscar usuarios por 'correo' y 'activo'."""
        email_field_name = 'correo'
        active_users = Cuenta._default_manager.filter(
            **{
                '%s__iexact' % email_field_name: email,
                'activo': True,
            }
        )
        return (u for u in active_users if u.has_usable_password())

    def save(self, domain_override=None,
             subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html',
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None):

        email = self.cleaned_data["email"]
        if not domain_override:
            current_site = request.get_host() if request else '127.0.0.1:8000'
            site_name = current_site
        else:
            current_site = domain_override
            site_name = domain_override

        for user in self.get_users(email):
            user_email = user.correo
            context = {
                'email': user_email,
                'domain': current_site,
                'site_name': site_name,
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': 'https' if use_https else 'http',
                **(extra_email_context or {}),
            }
            self.send_mail(
                subject_template_name, email_template_name, context, from_email,
                user_email, html_email_template_name=html_email_template_name,
            )


# --- PERFIL DE USUARIO ---
class PerfilUsuarioForm(forms.ModelForm):
    class Meta:
        model = Docente  # Modelo referencial
        fields = ['nombres', 'apellidos', 'cedula']
        widgets = {
            'nombres': forms.TextInput(attrs={'class': 'form-control'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control'}),
            'cedula': forms.TextInput(attrs={'class': 'form-control'}),
        }


# --- GESTIÓN DE VEHÍCULOS (CON VALIDACIÓN DE LICENCIA) ---
class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ['placa', 'modelo', 'tipoVehiculo', 'aforo', 'universidad', 'conductor', 'estado', 'condicion',
                  'disponibilidad']
        widgets = {
            'placa': forms.TextInput(attrs={'class': 'form-control'}),
            'modelo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipoVehiculo': forms.Select(attrs={'class': 'form-select'}),
            'aforo': forms.NumberInput(attrs={'class': 'form-control'}),
            'universidad': forms.Select(attrs={'class': 'form-select'}),
            'conductor': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select bg-light'}),
            'condicion': forms.Select(attrs={'class': 'form-select'}),
            'disponibilidad': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'conductor' in self.fields:
            self.fields['conductor'].queryset = self.fields['conductor'].queryset.filter(disponibilidad=True)

    def clean(self):
        cleaned_data = super().clean()
        conductor = cleaned_data.get('conductor')
        tipo_vehiculo = cleaned_data.get('tipoVehiculo')

        if conductor and tipo_vehiculo:
            licencia = conductor.tipoLicencia
            # REGLAS DE NEGOCIO:
            if tipo_vehiculo == 'BUS' and licencia not in ['D', 'E']:
                self.add_error('conductor', f"Un BUS requiere licencia Tipo D o E. El conductor tiene Tipo {licencia}.")
            elif tipo_vehiculo == 'BUSETA' and licencia not in ['D', 'E']:
                self.add_error('conductor',
                               f"Una BUSETA requiere licencia Tipo D o E. El conductor tiene Tipo {licencia}.")
            elif licencia not in ['C', 'D', 'E']:
                self.add_error('conductor', f"Licencia Tipo {licencia} no válida para transporte institucional.")

        return cleaned_data


# --- GESTIÓN DE RESERVAS ADMIN (CON VALIDACIÓN DE LICENCIA) ---
class GestionReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['estado', 'vehiculo', 'conductor']
        widgets = {
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'conductor': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        vehiculo = cleaned_data.get('vehiculo')
        conductor = cleaned_data.get('conductor')

        if vehiculo and conductor:
            tipo_vehiculo = vehiculo.tipoVehiculo
            licencia = conductor.tipoLicencia
            if tipo_vehiculo == 'BUS' and licencia not in ['D', 'E']:
                self.add_error('conductor', f"Error: Este conductor (Licencia {licencia}) no puede conducir un BUS.")
            elif tipo_vehiculo == 'BUSETA' and licencia not in ['D', 'E']:
                self.add_error('conductor',
                               f"Error: Este conductor (Licencia {licencia}) no puede conducir una BUSETA.")

        return cleaned_data


# --- SOLICITUD DE RESERVA (DOCENTE) ---
class ReservaForm(forms.ModelForm):
    carrera_filtro = forms.ChoiceField(
        choices=Carrera.choices, label="Filtrar Carrera", required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'onchange': 'filtrarEstudiantes()'})
    )
    estudiantes_seleccion = forms.ModelMultipleChoiceField(
        queryset=Estudiante.objects.all(), label="Seleccionar Estudiantes", required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'estudiante-checkbox'})
    )

    class Meta:
        model = Reserva
        fields = ['motivo', 'aforo', 'fechaInicio', 'fechaFin', 'destino_canton', 'destino_parroquia',
                  'destino_calle_principal', 'destino_calle_secundaria']
        widgets = {
            'motivo': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ej: Gira académica'}),
            'aforo': forms.NumberInput(attrs={'class': 'form-control'}),
            'fechaInicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'fechaFin': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'destino_canton': forms.TextInput(attrs={'class': 'form-control'}),
            'destino_parroquia': forms.TextInput(attrs={'class': 'form-control'}),
            'destino_calle_principal': forms.TextInput(attrs={'class': 'form-control'}),
            'destino_calle_secundaria': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        inicio = cleaned_data.get("fechaInicio")
        fin = cleaned_data.get("fechaFin")

        if inicio and fin:
            if inicio > fin:
                raise forms.ValidationError("La fecha de inicio no puede ser posterior a la fecha de fin.")
            if inicio < timezone.now():
                raise forms.ValidationError("No puedes crear reservas en el pasado.")
        return cleaned_data


# --- INFORME DE VIAJE (CONDUCTOR) ---
class InformeViajeForm(forms.ModelForm):
    class Meta:
        model = InformeViaje
        fields = ['kilometraje_final', 'nivel_combustible', 'novedades']
        widgets = {
            'kilometraje_final': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 120500'}),
            'nivel_combustible': forms.Select(attrs={'class': 'form-select'}),
            'novedades': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Novedades mecánicas o incidentes...'}),
        }

class LoginConCaptchaForm(AuthenticationForm):
    captcha = ReCaptchaField(
        label='',
        widget=ReCaptchaV2Checkbox(api_params={'hl': 'es'}),  # captcha en español
        error_messages={'required': 'Confirma que no eres un robot.'},
    )

User = get_user_model()

class RegistroUnlForm(UserCreationForm):
    username = forms.EmailField(required=True, label="Correo Institucional", widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'usuario@unl.edu.ec'}))
    nombres = forms.CharField(required=True, max_length=100, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombres completos'}))
    apellidos = forms.CharField(required=True, max_length=100, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Apellidos completos'}))
    cedula = forms.CharField(required=True, max_length=20, label="Cédula", widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 110xxxxxx'}))
    
    # VOLVEMOS A AGREGAR LOS CAMPOS PARA QUE EL HTML LOS PUEDA PINTAR
    facultad = forms.ChoiceField(
        choices=Facultad.choices,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    carrera = forms.ChoiceField(
        choices=Carrera.choices,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    tipo_licencia = forms.CharField(
        required=False,
        max_length=20,
        label="Tipo de Licencia (Solo Conductores)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Tipo E, Tipo D'})
    )

    class Meta:
        model = User
        fields = ['username']


    def clean_username(self):
        email = self.cleaned_data.get('username')
        if not email.endswith('@unl.edu.ec'):
            raise forms.ValidationError("Solo se permiten correos institucionales @unl.edu.ec")
        if User.objects.filter(correo=email).exists():
            raise forms.ValidationError("Este correo ya se encuentra registrado.")
        return email

    def clean_cedula(self):
        cedula = self.cleaned_data.get('cedula')
        if (Estudiante.objects.filter(cedula=cedula).exists() or 
            Docente.objects.filter(cedula=cedula).exists() or 
            Conductor.objects.filter(cedula=cedula).exists()):
            raise forms.ValidationError("Esta cédula ya se encuentra registrada en el sistema.")
        return cedula

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['username']
        user.correo = self.cleaned_data['username']
        user.nombres = self.cleaned_data['nombres']
        user.apellidos = self.cleaned_data['apellidos']
        user.cedula = self.cleaned_data['cedula']
        
        # Guardamos la licencia de forma segura en un atributo dinámico temporal de la cuenta
        user.tipo_licencia_temp = self.cleaned_data.get('tipo_licencia', '')
        
        user.activo = False  
        if commit:
            user.save()
        return user
