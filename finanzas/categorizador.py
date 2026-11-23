"""Motor de categorización automatizada basado en reglas y palabras clave."""

from .models import Categoria, ReglaCategorizacion

# Categorías de respaldo para movimientos que ninguna regla clasifica. Conservan
# el sentido (ingreso o egreso) del movimiento, de modo que este se contabilice
# en los indicadores aunque el usuario aún no lo haya clasificado.
GENERICA_INGRESO = "Otros ingresos"
GENERICA_EGRESO = "Otros egresos"


def sugerir_categoria(usuario, descripcion):
    """Devuelve la primera regla cuyo patrón aparece en la descripción.

    Se evalúa por prioridad ascendente. No emplea aprendizaje profundo ni
    modelos de lenguaje: es un motor determinista, auditable y explicable,
    acorde con la delimitación del proyecto.
    """
    texto = (descripcion or "").lower()
    for regla in ReglaCategorizacion.objects.filter(
        usuario=usuario
    ).select_related("categoria"):
        if regla.patron.lower() in texto:
            return regla
    return None


def aplicar(usuario, movimiento, guardar=True):
    """Asigna categoría al movimiento si alguna regla coincide."""
    if movimiento.categoria_id:
        return False
    regla = sugerir_categoria(usuario, movimiento.descripcion)
    if not regla:
        return False
    movimiento.categoria = regla.categoria
    movimiento.categorizado_automaticamente = True
    regla.veces_aplicada += 1
    if guardar:
        movimiento.save(update_fields=["categoria", "categorizado_automaticamente"])
        regla.save(update_fields=["veces_aplicada"])
    return True


def categoria_generica(usuario, es_ingreso):
    """Devuelve, creándola si no existe, la categoría de respaldo del sentido
    indicado."""
    nombre = GENERICA_INGRESO if es_ingreso else GENERICA_EGRESO
    tipo = Categoria.TIPO_INGRESO if es_ingreso else Categoria.TIPO_EGRESO
    cat, _ = Categoria.objects.get_or_create(
        usuario=usuario, nombre=nombre,
        defaults={"tipo": tipo, "naturaleza": Categoria.NATURALEZA_VARIABLE, "color": "#9CA3AF"},
    )
    return cat


def clasificar_o_respaldar(usuario, movimiento, es_ingreso):
    """Aplica las reglas; si ninguna coincide, asigna la categoría de respaldo.

    Devuelve "usuario" si el movimiento ya traía categoría, "regla" o "respaldo". La asignación de respaldo no se marca como
    categorización automática, para no inflar el indicador de cobertura del
    motor de reglas.
    """
    if movimiento.categoria_id:
        return "usuario"
    if aplicar(usuario, movimiento):
        return "regla"
    if not movimiento.categoria_id:
        movimiento.categoria = categoria_generica(usuario, es_ingreso)
        movimiento.save(update_fields=["categoria"])
    return "respaldo"
