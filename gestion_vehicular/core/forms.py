from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.core.exceptions import ValidationError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from core.models import Cuenta


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

    def clean_username(self):
        correo = self.cleaned_data.get('username')
        if correo and not correo.endswith('@unl.edu.ec'):
            msg = (
                "Acceso restringido: "
                "Solo se permiten correos institucionales (@unl.edu.ec)."
            )
            raise ValidationError(msg)
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
                subject_template_name,
                email_template_name,
                context,
                from_email,
                user_email,
                html_email_template_name=html_email_template_name,
            )
