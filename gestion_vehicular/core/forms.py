from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
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
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from anymail.message import AnymailMessage
from .models import (
    CARRERA_A_FACULTAD, Conductor, Facultad, Reserva,
    Vehiculo, Docente, Estudiante, Carrera, Cuenta, InformeViaje,
)
from .validaciones import correo_institucional_existe, nombres_desde_correo, validar_cedula


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

    def save(self, domain_override=None, subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html', use_https=False,
             token_generator=default_token_generator, from_email=None, request=None, 
             html_email_template_name=None, **kwargs):
        
        # Recuperamos el contexto extra enviado por Django si es que existe
        extra_email_context = kwargs.get('extra_email_context')

        for user in self.get_users(self.cleaned_data["email"]):
            context = {
                'email': user.correo,
                'domain': domain_override or (request.get_host() if request else ''),
                'site_name': 'Gestión de Transporte UNL',
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': token_generator.make_token(user),
                'protocol': 'https' if use_https or (request and request.is_secure()) else 'http',
            }
            
            # Si Django envió contexto extra (como en Django 6.x), lo unificamos
            if extra_email_context is not None:
                context.update(extra_email_context)
            
            subject = render_to_string(subject_template_name, context).strip()
            body = render_to_string(email_template_name, context)

            # FORZADO POR API HTTP DE BREVO (Inmune a los bloqueos de Render)
            message = AnymailMessage(
                subject=subject,
                body=body,
                from_email="Gestión de Transporte UNL <jorge.luzuriaga@unl.edu.ec>",
                to=[user.correo],
            )
            
            if html_email_template_name:
                html_email = render_to_string(html_email_template_name, context)
                message.attach_alternative(html_email, "text/html")
                
            message.send()


AYUDA_CONTRASENA = mark_safe(
    '<ul class="mb-0 ps-3">'
    '<li>No puede parecerse demasiado a tus datos personales.</li>'
    '<li>Debe tener al menos 8 caracteres.</li>'
    '<li>No puede ser una contraseña de uso muy común.</li>'
    '<li>No puede ser solo números.</li>'
    '</ul>'
)


class UnlSetPasswordForm(SetPasswordForm):
    error_messages = {
        'password_mismatch': 'Las contraseñas no coinciden.',
    }

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields['new_password1'].label = 'Nueva contraseña'
        self.fields['new_password1'].help_text = AYUDA_CONTRASENA
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Nueva contraseña',
        })
        self.fields['new_password2'].label = 'Confirmar nueva contraseña'
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Repite la nueva contraseña',
        })


class CarreraPorFacultadSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        facultad = CARRERA_A_FACULTAD.get(str(value))
        if facultad:
            option['attrs']['data-facultad'] = facultad
        return option


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
    error_messages = {
        'password_mismatch': 'Las contraseñas no coinciden.',
    }
    correo = forms.EmailField(
        required=True,
        label='Correo institucional',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'nombre.apellido@unl.edu.ec',
            'autocomplete': 'username',
        }),
    )
    correo_confirmacion = forms.EmailField(
        required=True,
        label='Confirmar correo institucional',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repite el correo institucional',
            'autocomplete': 'off',
        }),
    )
    nombres = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control bg-light', 'readonly': 'readonly'}),
    )
    apellidos = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control bg-light', 'readonly': 'readonly'}),
    )
    cedula = forms.CharField(
        required=True,
        max_length=10,
        label='Cédula',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '10 números',
            'maxlength': '10',
            'inputmode': 'numeric',
        }),
    )
    facultad = forms.ChoiceField(
        choices=[facultad for facultad in Facultad.choices if facultad[0] != Facultad.RNR],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    carrera = forms.ChoiceField(
        choices=Carrera.choices,
        widget=CarreraPorFacultadSelect(attrs={'class': 'form-select'}),
    )
    tipo_licencia = forms.ChoiceField(
        required=False,
        label='Tipo de licencia',
        choices=[
            ('', 'No aplica'),
            ('A', 'Tipo A'),
            ('B', 'Tipo B'),
            ('C', 'Tipo C'),
            ('D', 'Tipo D'),
            ('E', 'Tipo E'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = User
        fields = ['correo']

    def __init__(self, *args, verificar_correo=True, **kwargs):
        self.verificar_correo = verificar_correo
        super().__init__(*args, **kwargs)
        for nombre in ('password1', 'password2'):
            self.fields[nombre].widget.attrs.update({'class': 'form-control'})
        self.fields['password1'].label = 'Contraseña'
        self.fields['password1'].help_text = AYUDA_CONTRASENA
        self.fields['password2'].label = 'Confirmar contraseña'
        self.fields['password2'].help_text = 'Vuelve a escribir la contraseña.'

    def clean_correo(self):
        email = (self.cleaned_data.get('correo') or '').strip().lower()
        if not email.endswith('@unl.edu.ec'):
            raise forms.ValidationError('Solo se permiten correos institucionales @unl.edu.ec.')
        if User.objects.filter(correo__iexact=email).exists():
            raise forms.ValidationError('Este correo ya se encuentra registrado.')
        existe = correo_institucional_existe(email)
        if existe is False:
            raise forms.ValidationError('El correo no existe.')
        return email

    def clean_cedula(self):
        cedula = (self.cleaned_data.get('cedula') or '').strip()
        error = validar_cedula(cedula)
        if error:
            raise forms.ValidationError(error)
        if (Cuenta.objects.filter(cedula=cedula).exists() or
                Estudiante.objects.filter(cedula=cedula).exists() or
                Docente.objects.filter(cedula=cedula).exists() or
                Conductor.objects.filter(cedula=cedula).exists()):
            raise forms.ValidationError('Esta cédula ya se encuentra registrada en el sistema.')
        return cedula

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('correo')
        confirmacion = (cleaned.get('correo_confirmacion') or '').strip().lower()
        if email and confirmacion and email != confirmacion:
            self.add_error('correo_confirmacion', 'La confirmación no coincide con el correo institucional.')
        if email:
            nombres, apellidos = nombres_desde_correo(email)
            if not nombres or not apellidos:
                self.add_error(
                    'correo',
                    'El correo debe tener la forma nombre.apellido@unl.edu.ec. '
                    'Si incluye una inicial (nombre.x.apellido), esa letra se omite.',
                )
            else:
                cleaned['nombres'] = nombres
                cleaned['apellidos'] = apellidos
                self.instance.nombres = nombres
                self.instance.apellidos = apellidos
        facultad = cleaned.get('facultad')
        carrera = cleaned.get('carrera')
        if facultad and carrera and CARRERA_A_FACULTAD.get(carrera) != facultad:
            self.add_error('carrera', 'Esta carrera no pertenece a la facultad seleccionada.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.nombres = self.cleaned_data['nombres']
        user.apellidos = self.cleaned_data['apellidos']
        user.cedula = self.cleaned_data['cedula']
        user.facultad = self.cleaned_data['facultad']
        user.carrera = self.cleaned_data['carrera']
        user.tipo_licencia = self.cleaned_data.get('tipo_licencia') or ''
        user.correo_verificado = False
        user.activo = False
        if commit:
            user.save()
        return user