"""
Importación de movimientos desde archivos estructurados.

Cubre el nivel 2 del esquema de ingesta: archivos CSV y XLSX que el propio
usuario descarga de su banca electrónica y carga voluntariamente. No
constituye integración con instituciones financieras.
"""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import LoteImportacion, Movimiento

# Encabezados frecuentes en los archivos de la banca mexicana. Permiten
# proponer un mapeo inicial que el usuario puede corregir antes de confirmar
# (véase mapeo_desde_formulario).
PISTAS = {
    "fecha": ["fecha", "fecha de operacion", "fecha operacion", "fecha cargo", "date", "f. operacion"],
    "descripcion": ["descripcion", "concepto", "detalle", "referencia", "description", "movimiento"],
    "cargo": ["cargo", "retiro", "debito", "egreso", "salida"],
    "abono": ["abono", "deposito", "credito", "ingreso", "entrada"],
    "monto": ["monto", "importe", "amount", "valor", "cantidad"],
}

FORMATOS_FECHA = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y",
    "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d-%b-%Y",
]

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _norm(texto):
    t = (texto or "").strip().lower()
    for a, b in [("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


def leer_tabla(nombre, contenido):
    """Devuelve (encabezados, filas) desde un CSV o XLSX en memoria."""
    if nombre.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        hoja = wb[wb.sheetnames[0]]
        filas = [[c if c is not None else "" for c in fila]
                 for fila in hoja.iter_rows(values_only=True)]
        wb.close()
    else:
        texto = None
        for cod in ("utf-8-sig", "latin-1"):
            try:
                texto = contenido.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise ValueError("No fue posible decodificar el archivo.")
        delim = ";" if texto.count(";") > texto.count(",") else ","
        filas = [f for f in csv.reader(io.StringIO(texto), delimiter=delim)]

    # Localiza la fila de encabezados: la primera con dos o mas celdas no vacias
    inicio = 0
    for i, f in enumerate(filas[:25]):
        if sum(1 for c in f if str(c).strip()) >= 2:
            inicio = i
            break
    encabezados = [str(c).strip() for c in filas[inicio]]
    datos = [f for f in filas[inicio + 1:] if any(str(c).strip() for c in f)]
    return encabezados, datos


def filas_serializables(filas):
    """Convierte las celdas a texto para conservar la tabla en la sesión
    mientras el usuario revisa el mapeo. Las fechas de XLSX se expresan en
    formato ISO, que _a_fecha reconoce."""
    salida = []
    for fila in filas:
        nueva = []
        for c in fila:
            if isinstance(c, datetime):
                nueva.append(c.date().isoformat())
            elif isinstance(c, date):
                nueva.append(c.isoformat())
            else:
                nueva.append("" if c is None else str(c))
        salida.append(nueva)
    return salida


def proponer_mapeo(encabezados):
    """Sugiere que columna corresponde a cada campo del modelo."""
    mapeo = {}
    normalizados = [_norm(h) for h in encabezados]
    for campo, pistas in PISTAS.items():
        for i, h in enumerate(normalizados):
            if any(p in h for p in pistas):
                mapeo[campo] = i
                break
    return mapeo


def _a_fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    if not s:
        return None
    for f in FORMATOS_FECHA:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})[\s/-]([A-Za-z]{3})[\s/-](\d{2,4})", s)
    if m and _norm(m.group(2))[:3] in MESES:
        d, mes, a = int(m.group(1)), MESES[_norm(m.group(2))[:3]], int(m.group(3))
        return date(a if a > 100 else 2000 + a, mes, d)
    return None


def _a_monto(valor):
    if valor in (None, ""):
        return None
    s = str(valor).strip().replace("$", "").replace(" ", "")
    negativo = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        monto = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return -monto if negativo else monto


def extraer(encabezados, filas, mapeo):
    """Convierte las filas del archivo en movimientos preliminares.

    Devuelve (candidatos, descartados). Cada candidato trae fecha, descripcion,
    monto y si representa un ingreso.
    """
    candidatos, descartados = [], 0
    i_fecha = mapeo.get("fecha")
    i_desc = mapeo.get("descripcion")
    i_cargo, i_abono, i_monto = mapeo.get("cargo"), mapeo.get("abono"), mapeo.get("monto")

    for fila in filas:
        def celda(i):
            return fila[i] if i is not None and i < len(fila) else ""

        f = _a_fecha(celda(i_fecha))
        desc = str(celda(i_desc)).strip()

        if i_cargo is not None or i_abono is not None:
            cargo, abono = _a_monto(celda(i_cargo)), _a_monto(celda(i_abono))
            if abono:
                monto, es_ingreso = abs(abono), True
            elif cargo:
                monto, es_ingreso = abs(cargo), False
            else:
                monto, es_ingreso = None, False
        else:
            bruto = _a_monto(celda(i_monto))
            if bruto is None:
                monto, es_ingreso = None, False
            else:
                monto, es_ingreso = abs(bruto), bruto > 0

        if not f or not desc or not monto or monto <= 0:
            descartados += 1
            continue

        candidatos.append({"fecha": f, "descripcion": desc[:160],
                           "monto": monto, "es_ingreso": es_ingreso})
    return candidatos, descartados


def marcar_duplicados(usuario, candidatos):
    """Senala los candidatos que ya existen en la base del usuario.

    El criterio de identidad es la terna fecha, monto y descripcion, que evita
    duplicar al reimportar un periodo ya cargado.
    """
    if not candidatos:
        return candidatos
    fechas = [c["fecha"] for c in candidatos]
    existentes = set(
        Movimiento.objects.filter(
            usuario=usuario, fecha__gte=min(fechas), fecha__lte=max(fechas)
        ).values_list("fecha", "monto", "descripcion")
    )
    vistos = set()
    for c in candidatos:
        clave = (c["fecha"], c["monto"], c["descripcion"])
        c["duplicado"] = clave in existentes or clave in vistos
        vistos.add(clave)
    return candidatos


CAMPOS = ["fecha", "descripcion", "cargo", "abono", "monto"]


def mapeo_desde_formulario(datos, n_columnas):
    """Construye el mapeo a partir de la corrección hecha por el usuario.

    `datos` es un diccionario campo -> índice de columna en texto; el valor
    vacío indica que el campo no está presente en el archivo.
    """
    mapeo = {}
    for campo in CAMPOS:
        valor = str(datos.get(f"map_{campo}", "")).strip()
        if valor.isdigit() and int(valor) < n_columnas:
            mapeo[campo] = int(valor)
    return mapeo


def confirmar(usuario, nombre_archivo, formato, institucion, candidatos, detectados):
    """Guarda los movimientos aceptados y registra el lote de importacion.

    Cada movimiento pasa por el motor de reglas; si ninguna regla coincide, se
    le asigna la categoría de respaldo de su sentido (ingreso o egreso), que el
    archivo de origen sí permite conocer.
    """
    from .categorizador import clasificar_o_respaldar

    lote = LoteImportacion.objects.create(
        usuario=usuario, nombre_archivo=nombre_archivo[:160], formato=formato,
        institucion=institucion[:60], registros_detectados=detectados,
        registros_confirmados=len(candidatos),
    )
    guardados = 0
    for c in candidatos:
        mov = Movimiento(
            usuario=usuario, fecha=c["fecha"], descripcion=c["descripcion"],
            monto=c["monto"], origen=Movimiento.ORIGEN_ARCHIVO, lote=lote,
        )
        mov.save()
        clasificar_o_respaldar(usuario, mov, bool(c.get("es_ingreso")))
        guardados += 1
    return lote, guardados
