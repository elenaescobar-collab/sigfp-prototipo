"""
Asistente conversacional basado en comprensión de lenguaje natural.

Arquitectura de intenciones y entidades, no generativa. Emplea spaCy con el
modelo es_core_news_sm para normalizar y lematizar el enunciado del usuario,
clasifica la intención por coincidencia ponderada de lemas y extrae las
entidades de periodo y categoría. La respuesta se construye consultando la
base de datos del propio usuario.

No utiliza modelos de lenguaje de gran escala ni aprendizaje profundo: el
catálogo de intenciones es cerrado y cada respuesta es trazable hasta la
consulta que la produjo.
"""

import re
import unicodedata
from datetime import date

import spacy

from . import indicadores
from .models import Categoria, ConsultaAsistente

_NLP = None


def nlp():
    """Carga diferida del modelo de lenguaje."""
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("es_core_news_sm", disable=["ner", "parser"])
    return _NLP


def _sin_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def _raiz(palabra, n=4):
    """Trunca la palabra a su raíz aproximada.

    El modelo es_core_news_sm no lematiza de manera uniforme las formas
    verbales de primera persona en pretérito, frecuentes en este dominio
    ("ahorré" no se reduce a "ahorrar"). El truncamiento complementa al
    lematizador y se pondera con menor peso que la coincidencia exacta.
    """
    return palabra[:n] if len(palabra) > n else palabra


def _tercera_persona_preterito(palabra):
    """Detecta por sufijo la tercera persona del singular en pretérito
    ("ganó", "gastó", "cobró").

    Las consultas del dominio se refieren a las finanzas del propio usuario y
    se formulan en primera persona ("gané", "gasté"). Un verbo en tercera
    persona ("¿quién ganó el partido?") indica que el enunciado trata de otra
    cosa. Se decide por la forma superficial porque es_core_news_sm etiqueta
    de manera inconsistente la persona gramatical en este tiempo verbal
    ("gasté" aparece como tercera persona).
    """
    return len(palabra) > 3 and palabra.endswith("ó")


def lemas(texto):
    """Devuelve (lemas exactos, raíces) normalizados del enunciado.

    Los verbos en tercera persona del pretérito se excluyen, de modo que no
    activan intenciones referidas a las finanzas del usuario.
    """
    doc = nlp()(texto.lower())
    exactos, raices = set(), set()
    for t in doc:
        if t.is_punct or t.is_space or _tercera_persona_preterito(t.text):
            continue
        for forma in (t.lemma_.lower(), t.text.lower()):
            f = _sin_acentos(forma)
            exactos.add(f)
            raices.add(_raiz(f))
    return exactos, raices


# --------------------------------------------------------------- intenciones
# Cada intención declara lemas que la activan y lemas que la refuerzan.
INTENCIONES = [
    {"nombre": "gasto_total", "disparadores": {"gastar", "gasto", "egreso", "salir"},
     "refuerzos": {"cuanto", "total", "mes", "periodo"},
     "ejemplo": "Cuánto gasté este mes"},
    {"nombre": "gasto_por_categoria", "disparadores": {"gastar", "gasto"},
     "refuerzos": {"categoria", "en"}, "requiere_categoria": True,
     "ejemplo": "Cuánto gasté en supermercado"},
    {"nombre": "categoria_mayor", "disparadores": {"categoria", "rubro"},
     "refuerzos": {"mas", "mayor", "cual", "que"},
     "ejemplo": "En qué categoría gasté más"},
    {"nombre": "ingreso_total", "disparadores": {"ingresar", "ingreso", "ganar", "recibir", "cobrar"},
     "refuerzos": {"cuanto", "total", "mes"},
     "ejemplo": "Cuánto gané este mes"},
    {"nombre": "ahorro", "disparadores": {"ahorrar", "ahorro"},
     "refuerzos": {"cuanto", "tasa", "mes"},
     "ejemplo": "Cuánto ahorré este mes"},
    {"nombre": "comparar_periodos", "disparadores": {"comparar", "anterior", "pasado"},
     "refuerzos": {"mas", "menos", "que", "mes", "gastar"},
     "ejemplo": "Gasté más que el mes pasado"},
    {"nombre": "estado_presupuesto", "disparadores": {"presupuesto"},
     "refuerzos": {"ir", "bien", "cumplir", "exceder", "como"},
     "ejemplo": "Voy bien con mi presupuesto"},
    {"nombre": "avance_metas", "disparadores": {"meta", "objetivo"},
     "refuerzos": {"ahorro", "avance", "como", "ir"},
     "ejemplo": "Cómo va mi meta de ahorro"},
]

# Puntaje mínimo para aceptar una intención. Las consultas del dominio
# puntúan muy por encima; filtra coincidencias débiles por raíz.
UMBRAL = 2.0

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}


def extraer_periodo(texto, hoy=None):
    """Reconoce la entidad de periodo. Devuelve (anio, mes, etiqueta)."""
    hoy = hoy or date.today()
    t = _sin_acentos(texto.lower())
    anio, mes = hoy.year, hoy.month

    if re.search(r"\b(mes pasado|mes anterior|pasado mes)\b", t):
        return (anio - 1, 12, "el mes pasado") if mes == 1 else (anio, mes - 1, "el mes pasado")
    for nombre, num in MESES.items():
        if re.search(rf"\b{_sin_acentos(nombre)}\b", t):
            a = anio if num <= mes else anio - 1
            m = re.search(r"\b(20\d{2})\b", t)
            if m:
                a = int(m.group(1))
            return a, num, f"{nombre} de {a}"
    return anio, mes, "este mes"


def extraer_categoria(usuario, texto):
    """Reconoce la entidad de categoría contra las del usuario."""
    t = _sin_acentos(texto.lower())
    mejor = None
    for c in Categoria.objects.filter(usuario=usuario, activa=True):
        n = _sin_acentos(c.nombre.lower())
        if re.search(rf"\b{re.escape(n)}\b", t):
            if mejor is None or len(n) > len(_sin_acentos(mejor.nombre.lower())):
                mejor = c
    return mejor


def clasificar(texto, tiene_categoria):
    """Clasifica la intención por coincidencia ponderada de lemas y raíces.

    La coincidencia exacta de lema pesa más que la de raíz, de modo que el
    truncamiento amplía la cobertura sin desplazar una intención mejor
    sustentada.
    """
    exactos, raices = lemas(texto)
    puntajes = []
    for i in INTENCIONES:
        d_raiz = {_raiz(x) for x in i["disparadores"]}
        r_raiz = {_raiz(x) for x in i["refuerzos"]}
        if not (exactos & i["disparadores"]) and not (raices & d_raiz):
            continue
        p = (2.0 * len(exactos & i["disparadores"])
             + 1.2 * len(raices & d_raiz)
             + 1.0 * len(exactos & i["refuerzos"])
             + 0.6 * len(raices & r_raiz))
        if i.get("requiere_categoria"):
            if not tiene_categoria:
                continue
            p += 2.5
        puntajes.append((p, i["nombre"]))
    if not puntajes:
        return None, 0.0
    puntajes.sort(reverse=True)
    if puntajes[0][0] < UMBRAL:
        return None, puntajes[0][0]
    return puntajes[0][1], puntajes[0][0]


# ---------------------------------------------------------------- resolución
def _money(v):
    return f"${v:,.2f}"


def responder(usuario, texto):
    """Interpreta el enunciado y construye la respuesta con datos del usuario."""
    cat = extraer_categoria(usuario, texto)
    anio, mes, etiqueta = extraer_periodo(texto)
    intencion, score = clasificar(texto, cat is not None)

    if not intencion:
        ejemplos = " · ".join(i["ejemplo"] for i in INTENCIONES[:4])
        r = ("No identifiqué la consulta. Puedo responder preguntas como: " + ejemplos + ".")
        ConsultaAsistente.objects.create(usuario=usuario, texto=texto[:240],
                                         intencion_detectada="", respuesta=r, resuelta=False)
        return {"intencion": None, "entidades": {}, "respuesta": r, "resuelta": False}

    if intencion == "gasto_total":
        v = indicadores.egresos_del_mes(usuario, anio, mes)
        r = f"Durante {etiqueta} registraste egresos por {_money(v)}."
    elif intencion == "gasto_por_categoria":
        from django.db.models import Sum
        from calendar import monthrange
        ini, fin = date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])
        from .models import Movimiento
        v = Movimiento.objects.filter(usuario=usuario, categoria=cat,
                                      fecha__range=(ini, fin)).aggregate(t=Sum("monto"))["t"] or 0
        r = f"En {cat.nombre}, durante {etiqueta}, registraste {_money(v)}."
    elif intencion == "categoria_mayor":
        filas = indicadores.gasto_por_categoria(usuario, anio, mes)
        r = (f"Durante {etiqueta} tu mayor gasto fue {filas[0]['categoria']}, "
             f"con {_money(filas[0]['total'])}, el {filas[0]['porcentaje']*100:.1f} % del total."
             if filas else f"No hay egresos registrados en {etiqueta}.")
    elif intencion == "ingreso_total":
        v = indicadores.ingresos_del_mes(usuario, anio, mes)
        r = f"Durante {etiqueta} registraste ingresos por {_money(v)}."
    elif intencion == "ahorro":
        bal = indicadores.balance_del_mes(usuario, anio, mes)
        tasa = indicadores.tasa_de_ahorro(usuario, anio, mes)
        r = (f"Durante {etiqueta} tu balance fue {_money(bal)}"
             + (f", una tasa de ahorro de {tasa*100:.1f} %." if tasa is not None else "."))
    elif intencion == "comparar_periodos":
        var = indicadores.variacion_contra_mes_anterior(usuario, anio, mes)
        if var is None:
            r = "No hay datos suficientes del periodo anterior para comparar."
        else:
            sentido = "más" if var > 0 else "menos"
            r = (f"Durante {etiqueta} gastaste {abs(var)*100:.1f} % {sentido} "
                 f"que el periodo anterior.")
    elif intencion == "estado_presupuesto":
        ps = indicadores.cumplimiento_presupuestal(usuario, anio, mes)
        if not ps:
            r = f"No tienes presupuestos definidos para {etiqueta}."
        else:
            exc = [p for p in ps if p["excedido"]]
            r = (f"Excediste {len(exc)} de {len(ps)} presupuestos. El mayor exceso es "
                 f"{exc[0]['categoria']}, con {_money(exc[0]['gastado'])} sobre un límite de "
                 f"{_money(exc[0]['limite'])}." if exc else
                 f"Vas dentro de los {len(ps)} presupuestos definidos para {etiqueta}.")
    elif intencion == "avance_metas":
        ms = indicadores.avance_de_metas(usuario)
        r = ("; ".join(f"{m['nombre']}: {m['avance']*100:.1f} % ({_money(m['acumulado'])} "
                       f"de {_money(m['objetivo'])})" for m in ms) + "."
             if ms else "No tienes metas de ahorro activas.")
    else:
        r = "Consulta reconocida pero sin resolución definida."

    ConsultaAsistente.objects.create(usuario=usuario, texto=texto[:240],
                                     intencion_detectada=intencion, respuesta=r, resuelta=True)
    return {"intencion": intencion, "score": round(score, 2),
            "entidades": {"periodo": etiqueta, "categoria": cat.nombre if cat else None},
            "respuesta": r, "resuelta": True}
