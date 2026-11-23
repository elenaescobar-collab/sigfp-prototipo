"""
Modelo de datos del Sistema Inteligente de Gestión Financiera Personal.

Cada entidad responde a un requerimiento funcional o a un indicador del
módulo de inteligencia de negocios. No se incluyen campos sin uso definido.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Categoria(models.Model):
    """Clasificación de los movimientos. Sostiene el análisis por categoría
    del módulo de inteligencia de negocios."""

    TIPO_INGRESO = "ingreso"
    TIPO_EGRESO = "egreso"
    TIPOS = [(TIPO_INGRESO, "Ingreso"), (TIPO_EGRESO, "Egreso")]

    NATURALEZA_FIJO = "fijo"
    NATURALEZA_VARIABLE = "variable"
    NATURALEZAS = [
        (NATURALEZA_FIJO, "Fijo"),
        (NATURALEZA_VARIABLE, "Variable"),
    ]

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="categorias"
    )
    nombre = models.CharField(max_length=60)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    naturaleza = models.CharField(
        max_length=10,
        choices=NATURALEZAS,
        default=NATURALEZA_VARIABLE,
        help_text="Permite calcular la proporción del ingreso destinada a "
        "gastos fijos frente a variables.",
    )
    color = models.CharField(
        max_length=7, default="#6B7280", help_text="Color en las visualizaciones."
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["tipo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "nombre"], name="categoria_unica_por_usuario"
            )
        ]

    def __str__(self):
        return self.nombre


class ReglaCategorizacion(models.Model):
    """Regla que permite asignar categoría de forma automatizada a partir de
    la descripción del movimiento. Es el mecanismo de categorización del
    prototipo: reglas y diccionario de palabras clave, sin aprendizaje
    profundo."""

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="reglas"
    )
    patron = models.CharField(
        max_length=80,
        help_text="Texto que se busca dentro de la descripción del movimiento.",
    )
    categoria = models.ForeignKey(
        Categoria, on_delete=models.CASCADE, related_name="reglas"
    )
    prioridad = models.PositiveSmallIntegerField(
        default=100, help_text="Menor número se evalúa primero."
    )
    veces_aplicada = models.PositiveIntegerField(
        default=0,
        help_text="Permite depurar reglas que no se usan y medir la cobertura "
        "de la categorización automatizada.",
    )

    class Meta:
        verbose_name = "regla de categorización"
        verbose_name_plural = "reglas de categorización"
        ordering = ["prioridad", "patron"]

    def __str__(self):
        return f"{self.patron} → {self.categoria.nombre}"


class LoteImportacion(models.Model):
    """Registro de cada carga de archivo. Da trazabilidad al origen de los
    movimientos y permite reportar la tasa de extracción correcta por formato,
    que es uno de los resultados esperados del proyecto."""

    FORMATO_CSV = "csv"
    FORMATO_XLSX = "xlsx"
    FORMATO_PDF = "pdf"
    FORMATOS = [
        (FORMATO_CSV, "CSV"),
        (FORMATO_XLSX, "XLSX"),
        (FORMATO_PDF, "PDF de estado de cuenta"),
    ]

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="lotes"
    )
    nombre_archivo = models.CharField(max_length=160)
    formato = models.CharField(max_length=5, choices=FORMATOS)
    institucion = models.CharField(
        max_length=60,
        blank=True,
        help_text="Institución bancaria de origen, cuando aplica.",
    )
    fecha_carga = models.DateTimeField(default=timezone.now)
    registros_detectados = models.PositiveIntegerField(default=0)
    registros_confirmados = models.PositiveIntegerField(
        default=0,
        help_text="Movimientos que el usuario validó antes de almacenarlos.",
    )

    class Meta:
        verbose_name = "lote de importación"
        verbose_name_plural = "lotes de importación"
        ordering = ["-fecha_carga"]

    @property
    def tasa_extraccion(self):
        if not self.registros_detectados:
            return None
        return self.registros_confirmados / self.registros_detectados

    def __str__(self):
        return f"{self.nombre_archivo} ({self.get_formato_display()})"


class Movimiento(models.Model):
    """Entidad central del sistema. Cada registro conserva su origen para
    permitir auditar la calidad de la ingesta."""

    ORIGEN_MANUAL = "manual"
    ORIGEN_ARCHIVO = "archivo"
    ORIGEN_PDF = "pdf"
    ORIGENES = [
        (ORIGEN_MANUAL, "Captura manual"),
        (ORIGEN_ARCHIVO, "Importación de archivo"),
        (ORIGEN_PDF, "Extracción de PDF"),
    ]

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="movimientos"
    )
    fecha = models.DateField()
    descripcion = models.CharField(max_length=160)
    monto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Siempre positivo; el sentido lo determina el tipo de categoría.",
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name="movimientos",
        null=True,
        blank=True,
    )
    origen = models.CharField(
        max_length=10, choices=ORIGENES, default=ORIGEN_MANUAL
    )
    lote = models.ForeignKey(
        LoteImportacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos",
    )
    categorizado_automaticamente = models.BooleanField(
        default=False,
        help_text="Permite medir la cobertura de la categorización automatizada.",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        ordering = ["-fecha", "-creado_en"]
        indexes = [
            models.Index(fields=["usuario", "fecha"]),
            models.Index(fields=["usuario", "categoria"]),
        ]

    @property
    def es_ingreso(self):
        return self.categoria and self.categoria.tipo == Categoria.TIPO_INGRESO

    def __str__(self):
        return f"{self.fecha} · {self.descripcion} · ${self.monto}"


class Presupuesto(models.Model):
    """Límite de gasto por categoría y periodo. Sostiene el indicador de
    cumplimiento presupuestal."""

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="presupuestos"
    )
    categoria = models.ForeignKey(
        Categoria, on_delete=models.CASCADE, related_name="presupuestos"
    )
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    monto_limite = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "presupuesto"
        verbose_name_plural = "presupuestos"
        ordering = ["-anio", "-mes"]
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "categoria", "anio", "mes"],
                name="presupuesto_unico_por_periodo",
            )
        ]

    def __str__(self):
        return f"{self.categoria.nombre} {self.mes:02d}/{self.anio}"


class MetaAhorro(models.Model):
    """Objetivo de ahorro del usuario. Sostiene el indicador de avance de
    metas."""

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="metas"
    )
    nombre = models.CharField(max_length=80)
    monto_objetivo = models.DecimalField(max_digits=12, decimal_places=2)
    monto_acumulado = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    fecha_objetivo = models.DateField()
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "meta de ahorro"
        verbose_name_plural = "metas de ahorro"
        ordering = ["fecha_objetivo"]

    @property
    def avance(self):
        if not self.monto_objetivo:
            return 0
        return min(float(self.monto_acumulado / self.monto_objetivo), 1.0)

    def __str__(self):
        return self.nombre


class ConsultaAsistente(models.Model):
    """Bitácora de las consultas al asistente conversacional. Permite evaluar
    la cobertura del reconocimiento de intenciones durante la validación."""

    usuario = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="consultas"
    )
    texto = models.CharField(max_length=240)
    intencion_detectada = models.CharField(max_length=60, blank=True)
    respuesta = models.TextField(blank=True)
    resuelta = models.BooleanField(default=False)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "consulta al asistente"
        verbose_name_plural = "consultas al asistente"
        ordering = ["-fecha"]

    def __str__(self):
        return self.texto[:60]
