from django.contrib import admin

from .models import (
    Categoria,
    ConsultaAsistente,
    LoteImportacion,
    MetaAhorro,
    Movimiento,
    Presupuesto,
    ReglaCategorizacion,
)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "naturaleza", "usuario", "activa")
    list_filter = ("tipo", "naturaleza", "activa")
    search_fields = ("nombre",)


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "descripcion",
        "monto",
        "categoria",
        "origen",
        "categorizado_automaticamente",
    )
    list_filter = ("origen", "categorizado_automaticamente", "categoria__tipo")
    search_fields = ("descripcion",)
    date_hierarchy = "fecha"


@admin.register(ReglaCategorizacion)
class ReglaAdmin(admin.ModelAdmin):
    list_display = ("patron", "categoria", "prioridad", "veces_aplicada")
    list_filter = ("categoria",)


@admin.register(LoteImportacion)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        "nombre_archivo",
        "formato",
        "institucion",
        "fecha_carga",
        "registros_detectados",
        "registros_confirmados",
    )
    list_filter = ("formato", "institucion")


@admin.register(Presupuesto)
class PresupuestoAdmin(admin.ModelAdmin):
    list_display = ("categoria", "mes", "anio", "monto_limite")
    list_filter = ("anio", "mes")


@admin.register(MetaAhorro)
class MetaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "monto_objetivo", "monto_acumulado", "fecha_objetivo", "activa")


@admin.register(ConsultaAsistente)
class ConsultaAdmin(admin.ModelAdmin):
    list_display = ("texto", "intencion_detectada", "resuelta", "fecha")
    list_filter = ("resuelta", "intencion_detectada")
