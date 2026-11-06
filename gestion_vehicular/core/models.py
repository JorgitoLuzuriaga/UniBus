from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone

# --- MANAGER DE USUARIO ---
class CuentaManager(BaseUserManager):
    def create_user(self, correo, password=None, **extra_fields):
        if not correo:
            raise ValueError('El usuario debe tener un correo electrónico')
        correo = self.normalize_email(correo)
        user = self.model(correo=correo, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, correo, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(correo, password, **extra_fields)


# --- ENUMERACIONES ---
class TipoVehiculo(models.TextChoices):
    CAMIONETA = 'CAMIONETA', 'Camioneta'
    BUS = 'BUS', 'Bus'
    BUSETA = 'BUSETA', 'Buseta'
    CARRO = 'CARRO', 'Carro'


class EstadoReserva(models.TextChoices):
    ANULADA = 'ANULADA', 'Anulada'
    ESPERA_CONDUCTOR = 'ESPERA_CONDUCTOR', 'Esperando Confirmación de Conductor'
    CHOFER_RECHAZO = 'CHOFER_RECHAZO', 'Conductor Rechazó (Reasignar)'
    ESPERA_ADMIN = 'ESPERA_ADMIN', 'Esperando Aprobación Admin'
    ACEPTADA = 'ACEPTADA', 'Aceptada y Programada'
    RECHAZADA = 'RECHAZADA', 'Rechazada Definitivamente'
    FINALIZADA = 'FINALIZADA', 'Viaje Finalizado (Informe Entregado)'

class Facultad(models.TextChoices):
    RECURSOS_NO_RENOVABLES = 'RNR', 'Recursos No Renovables y Energía'
    OTRA = 'OTRA', 'Otra Facultad'


class Carrera(models.TextChoices):
    COMPUTACION = 'COMPUTACION', 'Computación'
    INGENIERIA_CIVIL = 'INGENIERIA_CIVIL', 'Ingeniería Civil'
    ELECTRICIDAD = 'ELECTRICIDAD', 'Electricidad'
    MINAS = 'MINAS', 'Minas'
    GEOLOGIA = 'GEOLOGIA', 'Geología'


class EstadoAsistencia(models.TextChoices):
    SIN_RESPUESTA = 'SIN_RESPUESTA', 'Sin Respuesta'
    CONFIRMADO = 'CONFIRMADO', 'Confirmado'
    RECHAZADO = 'RECHAZADO', 'Rechazado'


# Nuevos Enums para Gestión de Flota
class EstadoOperativo(models.TextChoices):
    ACTIVO = 'ACTIVO', 'Activo'
    EN_MANTENIMIENTO = 'MANTENIMIENTO', 'En Mantenimiento'
    FUERA_SERVICIO = 'FUERA_SERVICIO', 'Fuera de Servicio'


class CondicionVehiculo(models.TextChoices):
    EXCELENTE = 'EXCELENTE', 'Excelente'
    BUENA = 'BUENA', 'Buena'
    REGULAR = 'REGULAR', 'Regular'
    MALA = 'MALA', 'Mala'


# --- MODELOS PRINCIPALES ---
class Universidad(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    telefono = models.CharField(max_length=20)

    def __str__(self):
        return self.nombre


class Cuenta(AbstractBaseUser, PermissionsMixin):
    correo = models.EmailField(unique=True, verbose_name='Correo Electrónico')
    activo = models.BooleanField(default=False) # Empieza inactivo hasta que lo apruebes
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # NUEVOS CAMPOS: Para guardar los datos del registro antes de tener un rol
    nombres = models.CharField(max_length=100, blank=True, null=True)
    apellidos = models.CharField(max_length=100, blank=True, null=True)
    cedula = models.CharField(max_length=20, unique=True, blank=True, null=True)
    
    # Selector de Rol para el Administrador
    class RolesDisponibles(models.TextChoices):
        NINGUNO = 'NINGUNO', 'Pendiente de Asignación'
        ESTUDIANTE = 'ESTUDIANTE', 'Estudiante'
        DOCENTE = 'DOCENTE', 'Docente'
        CONDUCTOR = 'CONDUCTOR', 'Conductor'

    rol_asignado = models.CharField(
        max_length=20, 
        choices=RolesDisponibles.choices, 
        default=RolesDisponibles.NINGUNO
    )

    objects = CuentaManager()
    USERNAME_FIELD = 'correo'
    REQUIRED_FIELDS = []

    def get_rol_perfil(self):
        if not self.activo or self.rol_asignado == self.RolesDisponibles.NINGUNO:
            return 'Pendiente de Aprobación', None
        
        if self.rol_asignado == self.RolesDisponibles.ESTUDIANTE and hasattr(self, 'estudiante_perfil'):
            return 'Estudiante', self.estudiante_perfil
        elif self.rol_asignado == self.RolesDisponibles.DOCENTE and hasattr(self, 'docente_perfil'):
            return 'Docente', self.docente_perfil
        elif hasattr(self, 'administrador_perfil'):
            return 'Administrador', self.administrador_perfil
        elif hasattr(self, 'conductor_perfil'):
            return 'Conductor', self.conductor_perfil
        return 'Sin Perfil', None

    @property
    def rol_nombre(self):
        return self.get_rol_perfil()[0]

    @property
    def nombre_completo(self):
        if self.nombres and self.apellidos:
            return f"{self.nombres} {self.apellidos}"
        return self.correo



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


# --- HERENCIA DE PERFILES ---
class Administrador(Persona):
    fechaInicio = models.DateField()
    fechaFin = models.DateField(null=True, blank=True)


class Conductor(Persona):
    tipoLicencia = models.CharField(max_length=20)
    disponibilidad = models.BooleanField(default=True)


class Docente(Persona):
    facultad = models.CharField(max_length=50, choices=Facultad.choices)
    titulo = models.CharField(max_length=100)


class Estudiante(Persona):
    facultad = models.CharField(max_length=50, choices=Facultad.choices)
    carrera = models.CharField(max_length=50, choices=Carrera.choices, default=Carrera.COMPUTACION)


# --- MODELOS DE NEGOCIO ---
class Vehiculo(models.Model):
    placa = models.CharField(max_length=20, unique=True)
    modelo = models.CharField(max_length=50)
    tipoVehiculo = models.CharField(max_length=20, choices=TipoVehiculo.choices)
    aforo = models.IntegerField()
    universidad = models.ForeignKey(Universidad, on_delete=models.CASCADE, related_name='vehiculos')

    # Conductor asignado por defecto
    conductor = models.ForeignKey(Conductor, on_delete=models.SET_NULL, null=True, blank=True, related_name='vehiculos')

    # Estado y Condición (Gestión de Flota)
    estado = models.CharField(max_length=20, choices=EstadoOperativo.choices, default=EstadoOperativo.ACTIVO)
    condicion = models.CharField(max_length=20, choices=CondicionVehiculo.choices, default=CondicionVehiculo.BUENA)

    # Disponibilidad simple para filtros rápidos
    disponibilidad = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.tipoVehiculo} - {self.placa} ({self.get_estado_display()})"


class Reserva(models.Model):
    # ... (MANTENER CAMPOS EXISTENTES DE RESERVA) ...
    motivo = models.TextField()
    aforo = models.IntegerField()
    fechaInicio = models.DateTimeField()
    fechaFin = models.DateTimeField()
    destino_canton = models.CharField(max_length=100)
    destino_parroquia = models.CharField(max_length=100)
    destino_calle_principal = models.CharField(max_length=200)
    destino_calle_secundaria = models.CharField(max_length=200)

    estado = models.CharField(max_length=20, choices=EstadoReserva.choices, default=EstadoReserva.ESPERA_CONDUCTOR)
    solicitante = models.ForeignKey(Docente, on_delete=models.CASCADE, related_name='reservas_solicitadas')
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservas')
    conductor = models.ForeignKey(Conductor, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservas_asignadas')

    def __str__(self):
        return f"Reserva {self.id} - {self.destino_canton}"

class Asistencia(models.Model):
    # ... (MANTENER IGUAL) ...
    estado = models.CharField(max_length=20, choices=EstadoAsistencia.choices, default=EstadoAsistencia.SIN_RESPUESTA)
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='asistencias')
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='asistencias')

# --- NUEVO MODELO: INFORME DE VIAJE ---
class InformeViaje(models.Model):
    reserva = models.OneToOneField(Reserva, on_delete=models.CASCADE, related_name='informe')
    kilometraje_final = models.PositiveIntegerField(help_text="Kilometraje al terminar el viaje")
    nivel_combustible = models.CharField(max_length=50, choices=[
        ('LLENO', 'Lleno'), ('3/4', '3/4'), ('1/2', '1/2'), ('1/4', '1/4'), ('RESERVA', 'Reserva')
    ])
    novedades = models.TextField(blank=True, null=True, help_text="Incidentes o comentarios del viaje")
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Informe Reserva #{self.reserva.id}"

class Notificacion(models.Model):
    destinatario = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name='notificaciones')
    mensaje = models.CharField(max_length=255)
    leido = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Para {self.destinatario}: {self.mensaje}"


class Asistencia(models.Model):
    estado = models.CharField(max_length=20, choices=EstadoAsistencia.choices, default=EstadoAsistencia.SIN_RESPUESTA)
    fechaRegistro = models.DateTimeField(auto_now_add=True)
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='asistencias')
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name='asistencias')

    class Meta:
        unique_together = ('reserva', 'estudiante')