from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms
from core.models import (
    Cuenta,
    Administrador,
    Docente,
    Estudiante,
    Conductor,
)


# --- FORMULARIO PERSONALIZADO DE CUENTA ---
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


# --- CONFIGURACIÓN DE CUENTA EN DJANGO ADMIN ---
class CuentaAdmin(BaseUserAdmin):
    add_form = CuentaCreationForm
    ordering = ('correo',)
    list_display = (
        'correo',
        'rol_nombre',
        'activo',
        'is_staff',
        'is_superuser'
    )
    list_filter = ('activo', 'is_staff')

    fieldsets = (
        (None, {'fields': ('correo', 'password')}),
        ('Estado de la Cuenta', {'fields': ('activo',)}),
        (
            'Permisos de Acceso',
            {
                'fields': (
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                )
            }
        ),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('correo', 'password'),
        }),
    )

    search_fields = ('correo',)
    filter_horizontal = ('groups', 'user_permissions')
    list_per_page = 20


# --- REGISTRO DE MODELOS DEL MÓDULO DE LOGIN / USUARIOS ---
admin.site.register(Cuenta, CuentaAdmin)
admin.site.register(Administrador)
admin.site.register(Docente)
admin.site.register(Estudiante)
admin.site.register(Conductor)
