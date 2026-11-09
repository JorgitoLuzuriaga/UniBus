from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.safestring import mark_safe
from anymail.message import AnymailMessage
from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox

from .models import (
    CARRERA_A_FACULTAD, CARRERAS_POR_FACULTAD, Conductor, Facultad, Reserva,
    Vehiculo, Docente, Estudiante, Carrera, InformeViaje
)
from .validaciones import correo_institucional_existe, nombres_desde_correo, validar_cedula

User = get_user_model()

# --- AYUDA DE CONTRASEÑA GLOBAL ---
AYUDA_CONTRASENA = mark_safe(
    '<ul class="mb-0 ps-3">'
    '<li>No puede parecerse demasiado a tus datos personales.</li>'
    '<li>Debe tener al menos 8 caracteres.</li>'
    '<li>No puede ser una contraseña de uso muy común.</li>'
    '<li>No puede ser solo números.</li>'
    '</ul>'
)

# --- APLANADO DE CARRERAS ÚNICO ---
CARRERAS_UNIFICADAS = []
for lista_carreras in CARRERAS_POR_FACULTAD.values():
    for codigo, nombre_legible in lista_carreras:
        if (codigo, nombre_legible) not in CARRERAS_UNIFICADAS:
            CARRERAS_UNIFICADAS.append((codigo, nombre_legible))


# --- WIDGET PERSONALIZADO PARA SELECT EN EL FRONTEND ---
class CarreraPorFacultadSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        facultad = CARRERA_A_FACULTAD.get(str(value))
        if facultad:
            option['attrs']['data-facultad'] = facultad.value if hasattr(facultad, 'value') else str(facultad)
        return option


# --- 1. LOGIN PERSONALIZADO (CON CAPTCHA Y VALIDACIÓN CORRECTA) ---
class UnlAuthenticationForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'usuario@unl.edu.ec',
        'autofocus': True
    }), label="Correo Institucional")
    
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
        email = (self.cleaned_data.get('username') or '').strip().lower()
        if not email.endswith('@unl.edu.ec'):
            raise forms.ValidationError('Solo se permiten correos institucionales @unl.edu.ec.')
        return email


# --- 2. REGISTRO DE USUARIO UNL (CORREGIDO SIN DUPLICADOS) ---
class RegistroUnlForm(forms.ModelForm):
    error_messages = {
        'password_mismatch': 'Las contraseñas no coinciden.',
    }
    
    field_order = ['correo', 'nombres', 'apellidos', 'cedula', 'facultad', 'carrera', 'tipo_licencia', 'password1', 'password2']

    correo = forms.EmailField(
        required=True,
        label='Correo institucional',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'nombre.apellido@unl.edu.ec',
            'autocomplete': 'email',
        }),
    )
    nombres = forms.CharField(
        required=False,
        max_length=100,
        label='Nombres',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Se completa con tu correo',
            'autocomplete': 'given-name',
        }),
    )
    apellidos = forms.CharField(
        required=False,
        max_length=100,
        label='Apellidos',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Se completa con tu correo',
            'autocomplete': 'family-name',
        }),
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
        choices=[(fac.value, fac.label) for fac in Facultad if fac != Facultad.RNR],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    carrera = forms.ChoiceField(
        choices=CARRERAS_UNIFICADAS,
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
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text=AYUDA_CONTRASENA
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Vuelve a escribir la contraseña.'
    )

    class Meta:
        model = User
        fields = ['correo', 'nombres', 'apellidos', 'cedula', 'facultad', 'carrera', 'tipo_licencia']

    def __init__(self, *args, verificar_correo=True, **kwargs):
        self.verificar_correo = verificar_correo
        super().__init__(*args, **kwargs)

    def clean_correo(self):
        email = (self.cleaned_data.get('correo') or '').strip().lower()
        if not email.endswith('@unl.edu.ec'):
            raise forms.ValidationError('Solo se permiten correos institucionales @unl.edu.ec.')
        if User.objects.filter(correo__iexact=email).exists():
            raise forms.ValidationError('Este correo ya se encuentra registrado.')
        
        if self.verificar_correo:
            existe = correo_institucional_existe(email)
            if existe is False:
                raise forms.ValidationError('El correo no existe o no responde en el servidor de la UNL.')
        return email

    def clean_cedula(self):
        cedula = (self.cleaned_data.get('cedula') or '').strip()
        error = validar_cedula(cedula)
        if error:
            raise forms.ValidationError(error)
        if (User.objects.filter(cedula=cedula).exists() or
                Estudiante.objects.filter(cedula=cedula).exists() or
                Docente.objects.filter(cedula=cedula).exists() or
                Conductor.objects.filter(cedula=cedula).exists()):
            raise forms.ValidationError('Esta cédula ya se encuentra registrada en el sistema.')
        return cedula

    # Reemplaza tu método clean() por este que convierte los Enums de forma robusta:
    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('correo')
        
        nombres = (cleaned.get('nombres') or '').strip()
        apellidos = (cleaned.get('apellidos') or '').strip()
        if email and (not nombres or not apellidos):
            sugeridos_nombres, sugeridos_apellidos = nombres_desde_correo(email)
            nombres = nombres or sugeridos_nombres
            apellidos = apellidos or sugeridos_apellidos
            if hasattr(self.data, 'copy'):
                data = self.data.copy()
                data['nombres'] = nombres
                data['apellidos'] = apellidos
                self.data = data

        if not nombres:
            self.add_error('nombres', 'Ingresa tus nombres. Si el correo no los trae, escríbelos aquí.')
        if not apellidos:
            self.add_error('apellidos', 'Ingresa tus apellidos. Si el correo no los trae, escríbelos aquí.')

        cleaned['nombres'] = nombres
        cleaned['apellidos'] = apellidos
        self.instance.nombres = nombres
        self.instance.apellidos = apellidos
                
        facultad = cleaned.get('facultad')
        carrera = cleaned.get('carrera')
        
        # --- VALIDACIÓN ROBUSTA ANTE ENUMS ---
        if facultad and carrera:
            facultad_enum = CARRERA_A_FACULTAD.get(carrera)
            
            if facultad_enum:
                # Extraemos el valor de texto ('FARNR', 'FEIRNNR', etc.) sin importar si viene como Enum o String
                if hasattr(facultad_enum, 'value'):
                    facultad_esperada_str = str(facultad_enum.value)
                else:
                    facultad_esperada_str = str(facultad_enum)
            else:
                facultad_esperada_str = ""

            # Normalizamos ambos a strings limpios y en mayúsculas para evitar fallos de matching
            if facultad_esperada_str.strip().upper() != str(facultad).strip().upper():
                self.add_error('carrera', 'Esta carrera no pertenece a la facultad seleccionada.')
                
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            self.add_error('password2', self.error_messages['password_mismatch'])
        elif p1:
            try:
                validate_password(p1, self.instance)
            except ValidationError as exc:
                self.add_error('password1', exc)

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.correo = self.cleaned_data['correo']
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


# --- 3. RECUPERACIÓN DE CONTRASEÑA ---
class UnlPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email.endswith('@unl.edu.ec'):
            raise forms.ValidationError('Solo se permiten correos institucionales @unl.edu.ec.')
        return email

    def get_users(self, email):
        # También incluye cuentas que aún esperan la asignación de rol.
        usuarios = User._default_manager.filter(correo__iexact=email)
        return (u for u in usuarios if u.has_usable_password())

    def save(self, domain_override=None, subject_template_name='registration/password_reset_subject.txt',
             email_template_name='registration/password_reset_email.html', use_https=False,
             token_generator=default_token_generator, from_email=None, request=None, 
             html_email_template_name=None, **kwargs):
        
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
            
            if extra_email_context is not None:
                context.update(extra_email_context)
            
            subject = render_to_string(subject_template_name, context).strip()
            body = render_to_string(email_template_name, context)

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
# --- 4. SOLICITUD DE RESERVA (DOCENTE) ---
class ReservaForm(forms.ModelForm):
    carrera_filtro = forms.ChoiceField(
        choices=CARRERAS_UNIFICADAS, 
        label="Filtrar Carrera", 
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'onchange': 'filtrarEstudiantes()'})
    )
    estudiantes_seleccion = forms.ModelMultipleChoiceField(
        queryset=Estudiante.objects.all(), 
        label="Seleccionar Estudiantes", 
        required=False,
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


# --- 5. PERFIL DE USUARIO ---
class PerfilUsuarioForm(forms.ModelForm):
    class Meta:
        model = Docente  
        fields = ['nombres', 'apellidos', 'cedula']
        widgets = {
            'nombres': forms.TextInput(attrs={'class': 'form-control'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control'}),
            'cedula': forms.TextInput(attrs={'class': 'form-control'}),
        }


# --- 6. GESTIÓN DE VEHÍCULOS ---
class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ['placa', 'modelo', 'tipoVehiculo', 'aforo', 'universidad', 'conductor', 'estado', 'condicion', 'disponibilidad']
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
            if tipo_vehiculo == 'BUS' and licencia not in ['D', 'E']:
                self.add_error('conductor', f"Un BUS requiere licencia Tipo D o E. El conductor tiene Tipo {licencia}.")
            elif tipo_vehiculo == 'BUSETA' and licencia not in ['D', 'E']:
                self.add_error('conductor', f"Una BUSETA requiere licencia Tipo D o E. El conductor tiene Tipo {licencia}.")
            elif licencia not in ['C', 'D', 'E']:
                self.add_error('conductor', f"Licencia Tipo {licencia} no válida para transporte institucional.")

        return cleaned_data


# --- 7. GESTIÓN DE RESERVAS (ADMINISTRADOR) ---
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
                self.add_error('conductor', f"Error: Este conductor (Licencia {licencia}) no puede conducir una BUSETA.")

        return cleaned_data


# --- 8. INFORME DE VIAJE (CONDUCTOR) ---
class InformeViajeForm(forms.ModelForm):
    class Meta:
        model = InformeViaje
        fields = ['kilometraje_final', 'nivel_combustible', 'novedades']
        widgets = {
            'kilometraje_final': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 120500'}),
            'nivel_combustible': forms.Select(attrs={'class': 'form-select'}),
            'novedades': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Novedades mecánicas o incidentes...'}),
        }
