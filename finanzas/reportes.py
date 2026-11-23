"""
Reportes financieros exportables (RF13).

Reúnen en un solo documento los indicadores del periodo, la composición del
gasto, el cumplimiento presupuestal, el avance de metas y el detalle de
movimientos. Se generan en tres formatos: PDF para lectura y archivo, XLSX
para análisis posterior en hoja de cálculo, y CSV para portabilidad.

Todos los valores provienen de las mismas funciones del módulo de
indicadores que alimentan el tablero y el asistente, de modo que una cifra
es idéntica en las tres vistas.
"""

import csv
import io
from calendar import monthrange
from datetime import date

from . import indicadores
from .models import Movimiento

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def etiqueta_periodo(anio, mes):
    return f"{MESES_ES[mes - 1]} de {anio}"


def datos_reporte(usuario, anio, mes):
    """Reúne la información del periodo en una estructura independiente del
    formato de salida."""
    inicio, fin = date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])
    movs = (Movimiento.objects.filter(usuario=usuario, fecha__range=(inicio, fin))
            .select_related("categoria").order_by("fecha", "id"))
    return {
        "usuario": usuario.get_username(),
        "anio": anio,
        "mes": mes,
        "periodo": etiqueta_periodo(anio, mes),
        "generado": date.today(),
        "ingresos": indicadores.ingresos_del_mes(usuario, anio, mes),
        "egresos": indicadores.egresos_del_mes(usuario, anio, mes),
        "balance": indicadores.balance_del_mes(usuario, anio, mes),
        "tasa_ahorro": indicadores.tasa_de_ahorro(usuario, anio, mes),
        "proporcion_fijo": indicadores.proporcion_gasto_fijo(usuario, anio, mes),
        "variacion": indicadores.variacion_contra_mes_anterior(usuario, anio, mes),
        "categorias": indicadores.gasto_por_categoria(usuario, anio, mes),
        "presupuestos": indicadores.cumplimiento_presupuestal(usuario, anio, mes),
        "metas": indicadores.avance_de_metas(usuario),
        "movimientos": [
            {
                "fecha": m.fecha,
                "descripcion": m.descripcion,
                "categoria": m.categoria.nombre if m.categoria else "Sin categoría",
                "tipo": "Ingreso" if m.es_ingreso else "Egreso",
                "monto": m.monto,
                "origen": m.get_origen_display(),
            }
            for m in movs
        ],
    }


def _pct(v):
    return "—" if v is None else f"{v * 100:.1f} %"


def _dinero(v):
    return f"${v:,.2f}"


def resumen_filas(d):
    """Filas del resumen de indicadores, compartidas por todos los formatos."""
    return [
        ("Ingresos del periodo", _dinero(d["ingresos"])),
        ("Egresos del periodo", _dinero(d["egresos"])),
        ("Balance", _dinero(d["balance"])),
        ("Tasa de ahorro", _pct(d["tasa_ahorro"])),
        ("Proporción de gasto fijo", _pct(d["proporcion_fijo"])),
        ("Variación del egreso contra el mes anterior", _pct(d["variacion"])),
        ("Movimientos registrados", str(len(d["movimientos"]))),
    ]


# ------------------------------------------------------------------- CSV
def a_csv(d):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fecha", "descripcion", "categoria", "tipo", "monto", "origen"])
    for m in d["movimientos"]:
        w.writerow([m["fecha"].isoformat(), m["descripcion"], m["categoria"],
                    m["tipo"], f"{m['monto']:.2f}", m["origen"]])
    # BOM para que Excel reconozca los acentos al abrir el archivo.
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ------------------------------------------------------------------ XLSX
def a_xlsx(d):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    encabezado = PatternFill("solid", fgColor="1F4E79")
    blanca = Font(bold=True, color="FFFFFF")

    def cabecera(ws, fila, textos):
        for i, t in enumerate(textos, start=1):
            c = ws.cell(row=fila, column=i, value=t)
            c.font, c.fill = blanca, encabezado
            c.alignment = Alignment(vertical="center")

    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "Reporte financiero personal"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Periodo: {d['periodo']}"
    ws["A3"] = f"Generado el {d['generado'].strftime('%d/%m/%Y')} · usuario {d['usuario']}"
    cabecera(ws, 5, ["Indicador", "Valor"])
    for i, (k, v) in enumerate(resumen_filas(d), start=6):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 20

    ws = wb.create_sheet("Gasto por categoría")
    cabecera(ws, 1, ["Categoría", "Total", "Porcentaje del egreso"])
    for i, c in enumerate(d["categorias"], start=2):
        ws.cell(row=i, column=1, value=c["categoria"])
        ws.cell(row=i, column=2, value=float(c["total"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=3, value=c["porcentaje"]).number_format = "0.0%"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 22

    ws = wb.create_sheet("Presupuestos")
    cabecera(ws, 1, ["Categoría", "Límite", "Gastado", "Uso", "Estado"])
    for i, p in enumerate(d["presupuestos"], start=2):
        ws.cell(row=i, column=1, value=p["categoria"])
        ws.cell(row=i, column=2, value=float(p["limite"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=3, value=float(p["gastado"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=4, value=p["uso"]).number_format = "0.0%"
        ws.cell(row=i, column=5, value="Excedido" if p["excedido"] else "Dentro del límite")
    for col, w in zip("ABCDE", (28, 14, 14, 10, 18)):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Metas de ahorro")
    cabecera(ws, 1, ["Meta", "Objetivo", "Acumulado", "Avance", "Fecha objetivo"])
    for i, m in enumerate(d["metas"], start=2):
        ws.cell(row=i, column=1, value=m["nombre"])
        ws.cell(row=i, column=2, value=float(m["objetivo"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=3, value=float(m["acumulado"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=4, value=m["avance"]).number_format = "0.0%"
        ws.cell(row=i, column=5, value=m["fecha_objetivo"]).number_format = "dd/mm/yyyy"
    for col, w in zip("ABCDE", (28, 14, 14, 10, 16)):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Movimientos")
    cabecera(ws, 1, ["Fecha", "Descripción", "Categoría", "Tipo", "Monto", "Origen"])
    for i, m in enumerate(d["movimientos"], start=2):
        ws.cell(row=i, column=1, value=m["fecha"]).number_format = "dd/mm/yyyy"
        ws.cell(row=i, column=2, value=m["descripcion"])
        ws.cell(row=i, column=3, value=m["categoria"])
        ws.cell(row=i, column=4, value=m["tipo"])
        ws.cell(row=i, column=5, value=float(m["monto"])).number_format = '"$"#,##0.00'
        ws.cell(row=i, column=6, value=m["origen"])
    for col, w in zip("ABCDEF", (12, 44, 22, 10, 14, 22)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------- PDF
def a_pdf(d):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (CondPageBreak, LongTable, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"Reporte financiero · {d['periodo']}")
    est = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=est["Title"], fontSize=17, spaceAfter=4)
    sub = ParagraphStyle("s", parent=est["Normal"], textColor=colors.HexColor("#4A5565"), fontSize=9.5)
    _h2 = ParagraphStyle("h2", parent=est["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6,
                         textColor=colors.HexColor("#1F4E79"), keepWithNext=1)
    celda = ParagraphStyle("c", parent=est["Normal"], fontSize=8.5, leading=10.5)
    azul = colors.HexColor("#1F4E79")

    class Encabezado(Paragraph):
        """Título de sección que no queda huérfano al pie de página."""
        def __init__(self, texto, estilo):
            super().__init__(texto, _h2 if estilo == "h2" else estilo)

    def tabla(filas, anchos, alinear_derecha=(), clase=Table):
        t = clase(filas, colWidths=anchos, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), azul),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9CFD8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for col in alinear_derecha:
            estilo.append(("ALIGN", (col, 1), (col, -1), "RIGHT"))
        t.setStyle(TableStyle(estilo))
        return t

    h = [Paragraph("Reporte financiero personal", titulo),
         Paragraph(f"Periodo: {d['periodo']} · generado el {d['generado'].strftime('%d/%m/%Y')} "
                   f"· usuario {d['usuario']}", sub),
         Spacer(1, 10),
         Paragraph("Resumen de indicadores", _h2),
         tabla([["Indicador", "Valor"]] + [list(r) for r in resumen_filas(d)],
               [11 * cm, 5.5 * cm], alinear_derecha=(1,))]

    h.append(Encabezado("Gasto por categoría", "h2"))
    if d["categorias"]:
        h.append(tabla([["Categoría", "Total", "Porcentaje"]] +
                       [[c["categoria"], _dinero(c["total"]), _pct(c["porcentaje"])] for c in d["categorias"]],
                       [9 * cm, 4 * cm, 3.5 * cm], alinear_derecha=(1, 2)))
    else:
        h.append(Paragraph("No hay egresos registrados en el periodo.", sub))

    h.append(Encabezado("Cumplimiento presupuestal", "h2"))
    if d["presupuestos"]:
        h.append(tabla([["Categoría", "Límite", "Gastado", "Uso", "Estado"]] +
                       [[p["categoria"], _dinero(p["limite"]), _dinero(p["gastado"]), _pct(p["uso"]),
                         "Excedido" if p["excedido"] else "Dentro del límite"] for p in d["presupuestos"]],
                       [5 * cm, 3 * cm, 3 * cm, 2 * cm, 3.5 * cm], alinear_derecha=(1, 2, 3)))
    else:
        h.append(Paragraph("No hay presupuestos definidos para el periodo.", sub))

    h.append(Encabezado("Metas de ahorro", "h2"))
    if d["metas"]:
        h.append(tabla([["Meta", "Objetivo", "Acumulado", "Avance", "Fecha objetivo"]] +
                       [[m["nombre"], _dinero(m["objetivo"]), _dinero(m["acumulado"]), _pct(m["avance"]),
                         m["fecha_objetivo"].strftime("%d/%m/%Y")] for m in d["metas"]],
                       [5 * cm, 3 * cm, 3 * cm, 2 * cm, 3.5 * cm], alinear_derecha=(1, 2, 3)))
    else:
        h.append(Paragraph("No hay metas de ahorro activas.", sub))

    h.append(Encabezado("Detalle de movimientos", "h2"))
    if d["movimientos"]:
        filas = [["Fecha", "Descripción", "Categoría", "Tipo", "Monto"]] + [
            [m["fecha"].strftime("%d/%m/%Y"), Paragraph(m["descripcion"], celda),
             Paragraph(m["categoria"], celda), m["tipo"], _dinero(m["monto"])]
            for m in d["movimientos"]]
        h.append(tabla(filas, [2.1 * cm, 6.6 * cm, 3.6 * cm, 1.7 * cm, 2.5 * cm],
                       alinear_derecha=(4,), clase=LongTable))
    else:
        h.append(Paragraph("No hay movimientos en el periodo.", sub))

    def pie(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(2 * cm, 1.2 * cm, "Sistema Inteligente de Gestión Financiera Personal · prototipo académico")
        canvas.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(h, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()
