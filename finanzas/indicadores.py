"""
Servicios de inteligencia de negocios.

Cada función implementa un indicador del catálogo. Se documenta su fórmula y
la fuente de datos, de modo que el módulo pueda reportarse en el capítulo de
diseño sin reconstruir la lógica.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from .models import Categoria, Movimiento, Presupuesto, MetaAhorro


def _rango_mes(anio, mes):
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def _suma(usuario, anio, mes, tipo, naturaleza=None):
    inicio, fin = _rango_mes(anio, mes)
    qs = Movimiento.objects.filter(
        usuario=usuario,
        fecha__range=(inicio, fin),
        categoria__tipo=tipo,
    )
    if naturaleza:
        qs = qs.filter(categoria__naturaleza=naturaleza)
    return qs.aggregate(t=Sum("monto"))["t"] or Decimal("0.00")


def ingresos_del_mes(usuario, anio, mes):
    """Suma de movimientos cuya categoría es de tipo ingreso en el periodo."""
    return _suma(usuario, anio, mes, Categoria.TIPO_INGRESO)


def egresos_del_mes(usuario, anio, mes):
    """Suma de movimientos cuya categoría es de tipo egreso en el periodo."""
    return _suma(usuario, anio, mes, Categoria.TIPO_EGRESO)


def balance_del_mes(usuario, anio, mes):
    """Ingresos menos egresos del periodo."""
    return ingresos_del_mes(usuario, anio, mes) - egresos_del_mes(usuario, anio, mes)


def tasa_de_ahorro(usuario, anio, mes):
    """(Ingresos - Egresos) / Ingresos. Expresa qué proporción del ingreso
    del periodo no fue consumida. Devuelve None si no hubo ingresos."""
    ingresos = ingresos_del_mes(usuario, anio, mes)
    if not ingresos:
        return None
    return float((ingresos - egresos_del_mes(usuario, anio, mes)) / ingresos)


def proporcion_gasto_fijo(usuario, anio, mes):
    """Egresos de categorías fijas / egresos totales del periodo. Indica la
    rigidez de la estructura de gasto."""
    total = egresos_del_mes(usuario, anio, mes)
    if not total:
        return None
    fijos = _suma(
        usuario, anio, mes, Categoria.TIPO_EGRESO, Categoria.NATURALEZA_FIJO
    )
    return float(fijos / total)


def gasto_por_categoria(usuario, anio, mes):
    """Distribución del egreso por categoría en el periodo, ordenada de mayor
    a menor. Alimenta la visualización de composición del gasto."""
    inicio, fin = _rango_mes(anio, mes)
    filas = (
        Movimiento.objects.filter(
            usuario=usuario,
            fecha__range=(inicio, fin),
            categoria__tipo=Categoria.TIPO_EGRESO,
        )
        .values("categoria__nombre", "categoria__color")
        .annotate(total=Sum("monto"))
        .order_by("-total")
    )
    total = sum((f["total"] for f in filas), Decimal("0.00"))
    return [
        {
            "categoria": f["categoria__nombre"],
            "color": f["categoria__color"],
            "total": f["total"],
            "porcentaje": float(f["total"] / total) if total else 0,
        }
        for f in filas
    ]


def variacion_contra_mes_anterior(usuario, anio, mes):
    """Variación relativa del egreso respecto del periodo inmediato anterior.
    Es el indicador de comparación temporal del tablero."""
    anterior_anio, anterior_mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    actual = egresos_del_mes(usuario, anio, mes)
    anterior = egresos_del_mes(usuario, anterior_anio, anterior_mes)
    if not anterior:
        return None
    return float((actual - anterior) / anterior)


def cumplimiento_presupuestal(usuario, anio, mes):
    """Para cada presupuesto del periodo, compara el gasto ejecutado contra el
    límite definido. Sostiene el seguimiento de presupuestos."""
    inicio, fin = _rango_mes(anio, mes)
    resultado = []
    for p in Presupuesto.objects.filter(
        usuario=usuario, anio=anio, mes=mes
    ).select_related("categoria"):
        gastado = Movimiento.objects.filter(
            usuario=usuario, categoria=p.categoria, fecha__range=(inicio, fin)
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0.00")
        resultado.append(
            {
                "categoria": p.categoria.nombre,
                "limite": p.monto_limite,
                "gastado": gastado,
                "uso": float(gastado / p.monto_limite) if p.monto_limite else 0,
                "excedido": gastado > p.monto_limite,
            }
        )
    return sorted(resultado, key=lambda r: r["uso"], reverse=True)


def avance_de_metas(usuario):
    """Avance de cada meta de ahorro activa."""
    return [
        {
            "nombre": m.nombre,
            "objetivo": m.monto_objetivo,
            "acumulado": m.monto_acumulado,
            "avance": m.avance,
            "fecha_objetivo": m.fecha_objetivo,
        }
        for m in MetaAhorro.objects.filter(usuario=usuario, activa=True)
    ]


def serie_mensual(usuario, meses=6, referencia=None):
    """Serie de ingresos y egresos de los últimos periodos. Alimenta la
    visualización de evolución temporal."""
    referencia = referencia or date.today()
    anio, mes = referencia.year, referencia.month
    serie = []
    for _ in range(meses):
        serie.append(
            {
                "etiqueta": f"{mes:02d}/{anio}",
                "ingresos": ingresos_del_mes(usuario, anio, mes),
                "egresos": egresos_del_mes(usuario, anio, mes),
            }
        )
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    return list(reversed(serie))


def cobertura_categorizacion(usuario):
    """Proporción de movimientos clasificados automáticamente. Mide la
    efectividad del motor de reglas y es un resultado reportable."""
    total = Movimiento.objects.filter(usuario=usuario).count()
    if not total:
        return None
    automaticos = Movimiento.objects.filter(
        usuario=usuario, categorizado_automaticamente=True
    ).count()
    return automaticos / total
