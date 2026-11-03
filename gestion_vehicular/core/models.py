from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone

# --- MANAGER DE USUARIO ---
class CuentaManager(BaseUserManager):
    def create_user(self, correo, password=None, **extra_fields):
        if not correo:
            raise ValueError('El usuario debe tener un correo electrónico institucional')
        correo = self.normalize_email(correo)
        user = self.model(correo=correo, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, correo, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(correo, password, **extra_fields)


# --- ENUMERACIONES INSTITUCIONALES ---
class Facultad(models.TextChoices):
    RECURSOS_NO_RENOVABLES = 'RNR', 'Recursos No Renovables y Energía'
    EDUCACION = 'EDUCACION', 'Educación, el Arte y la Comunicación'
    SALUD = 'SALUD', 'Salud Humana'
    AGROPECUARIA = 'AGROPECUARIA', 'Agropecuaria y de Recursos Naturales Renovables'
    JURIDICA = 'JURIDICA', 'Jurídica, Social y Administrativa'
    OTRA = 'OTRA', 'Otra Facultad'


class Carrera(models.TextChoices):
    COMPUTACION = 'COMPUTACION', 'Computación'
    INGENIERIA_CIVIL = 'INGENIERIA_CIVIL', 'Ingeniería Civil'
    ELECTRICIDAD = 'ELECTRICIDAD', 'Electricidad'
    MINAS = 'MINAS', 'Minas'
    GEOLOGIA = 'GEOLOGIA', 'Geología'


# --- MODELO PRINCIPAL DE CUENTA (AUTH USER) ---
class Cuenta(AbstractBaseUser, PermissionsMixin):
    correo = models.EmailField(unique=True, verbose_name='Correo Electrónico Institucional')
    activo = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CuentaManager()

    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.correo

    # --- MÉTODOS DE ROL Y PERFIL ---
    def get_rol_perfil(self):
        """Devuelve una tupla (NombreRol, ObjetoPerfil)"""
        if hasattr(self, 'administrador_perfil'):
            return 'Administrador', self.administrador_perfil
        elif hasattr(self, 'docente_perfil'):
            return 'Docente', self.docente_perfil
        elif hasattr(self, 'estudiante_perfil'):
            return 'Estudiante', self.estudiante_perfil
        elif hasattr(self, 'conductor_perfil'):
            return 'Conductor', self.conductor_perfil
        elif self.is_superuser:
            return 'Superadministrador', None
        return 'Sin Perfil', None

    @property
    def rol_nombre(self):
        return self.get_rol_perfil()[0]

    @property
    def nombre_completo(self):
        perfil = self.get_rol_perfil()[1]
        return perfil.getNombreCompleto() if perfil else self.correo


# --- CLASE BASE DE PERSONA ---
class Persona(models.Model):
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20, unique=True)
    cuenta = models.OneToOneField(Cuenta, on_delete=models.CASCADE, related_name='%(class)s_perfil')

    class Meta:
        abstract = True

    def getNombreCompleto(self):
        return f"{self.nombres} {self.apellidos}"

    def __str__(self):
        return self.getNombreCompleto()


# --- PERFILES POR ROL ---
class Administrador(Persona):
    fechaInicio = models.DateField(default=timezone.now)
    fechaFin = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Administrador'
        verbose_name_plural = 'Administradores'


class Docente(Persona):
    facultad = models.CharField(max_length=50, choices=Facultad.choices, default=Facultad.RECURSOS_NO_RENOVABLES)
    titulo = models.CharField(max_length=100, default='Docente')

    class Meta:
        verbose_name = 'Docente'
        verbose_name_plural = 'Docentes'


class Estudiante(Persona):
    facultad = models.CharField(max_length=50, choices=Facultad.choices, default=Facultad.RECURSOS_NO_RENOVABLES)
    carrera = models.CharField(max_length=50, choices=Carrera.choices, default=Carrera.COMPUTACION)

    class Meta:
        verbose_name = 'Estudiante'
        verbose_name_plural = 'Estudiantes'


class Conductor(Persona):
    tipoLicencia = models.CharField(max_length=20, default='Tipo E')
    disponibilidad = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Conductor'
        verbose_name_plural = 'Conductores'