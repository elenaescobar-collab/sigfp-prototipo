from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from . import indicadores
from .categorizador import clasificar_o_respaldar
from .forms import MovimientoForm
from .models import Categoria, ConsultaAsistente, LoteImportacion, Movimiento


def _periodo(request):
    hoy = date.today()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month
    return anio, mes


@login_required
def tablero(request):
    """Tablero de inteligencia de negocios."""
    u = request.user
    anio, mes = _periodo(request)

    ingresos = indicadores.ingresos_del_mes(u, anio, mes)
    egresos = indicadores.egresos_del_mes(u, anio, mes)
    serie = indicadores.serie_mensual(u, meses=6, referencia=date(anio, mes, 1))

    # Geometría de la gráfica de barras (SVG de 660x170, base en y=134).
    tope = max([max(s["ingresos"], s["egresos"]) for s in serie] + [1])
    BASE, ALTO, PASO, X0 = 134, 108, 98, 48
    serie_svg = []
    for i, s in enumerate(serie):
        h_ing = int(float(s["ingresos"]) / float(tope) * ALTO)
        h_egr = int(float(s["egresos"]) / float(tope) * ALTO)
        x = X0 + i * PASO
        serie_svg.append(
            {
                "etiqueta": s["etiqueta"],
                "h_ing": h_ing,
                "h_egr": h_egr,
                "y_ing": BASE - h_ing,
                "y_egr": BASE - h_egr,
                "x_ing": x,
                "x_egr": x + 22,
                "x_lbl": x + 20,
            }
        )

    tasa_ahorro = indicadores.tasa_de_ahorro(u, anio, mes)
    proporcion_fijo = indicadores.proporcion_gasto_fijo(u, anio, mes)
    variacion = indicadores.variacion_contra_mes_anterior(u, anio, mes)
    cobertura = indicadores.cobertura_categorizacion(u)

    def pct(v):
        return None if v is None else round(abs(v) * 100, 1)

    contexto = {
        "anio": anio,
        "mes": mes,
        "etiqueta_periodo": f"{mes:02d}/{anio}",
        "ingresos": ingresos,
        "egresos": egresos,
        "balance": ingresos - egresos,
        "tasa_ahorro": tasa_ahorro,
        "proporcion_fijo": proporcion_fijo,
        "variacion": variacion,
        "pct_ahorro": pct(tasa_ahorro),
        "pct_fijo": pct(proporcion_fijo),
        "pct_variacion": pct(variacion),
        "pct_cobertura": pct(cobertura),
        "por_categoria": [
            {**f, "pct": round(f["porcentaje"] * 100, 1)}
            for f in indicadores.gasto_por_categoria(u, anio, mes)
        ],
        "presupuestos": [
            {
                **p,
                "pct": round(p["uso"] * 100, 1),
                "pct_barra": round(min(p["uso"], 1.0) * 100, 1),
            }
            for p in indicadores.cumplimiento_presupuestal(u, anio, mes)
        ],
        "metas": [
            {**m, "pct": round(m["avance"] * 100, 1)}
            for m in indicadores.avance_de_metas(u)
        ],
        "cobertura": cobertura,
        "serie": serie_svg,
    }
    return render(request, "finanzas/tablero.html", contexto)


@login_required
def movimientos(request):
    """Registro de ingresos y egresos con categorización automatizada.

    La captura se valida con un formulario de Django, que aplica en el
    servidor los validadores del modelo (monto mayor o igual a 0.01).
    """
    u = request.user
    mensaje = None
    if request.method == "POST":
        form = MovimientoForm(request.POST, usuario=u)
        if form.is_valid():
            mov = form.save(commit=False)
            mov.usuario = u
            mov.origen = Movimiento.ORIGEN_MANUAL
            mov.save()
            resultado = clasificar_o_respaldar(
                u, mov, form.cleaned_data["sentido"] == Categoria.TIPO_INGRESO)
            request.session["aviso_mov"] = {
                "usuario": "Movimiento registrado con la categoría que elegiste.",
                "regla": f"Movimiento registrado y clasificado automáticamente como {mov.categoria.nombre}.",
                "respaldo": f"Ninguna regla coincidió; se registró en {mov.categoria.nombre}. "
                            "Puedes crear una regla en Administración para clasificarlo en adelante.",
            }[resultado]
            return redirect("movimientos")
    else:
        form = MovimientoForm(usuario=u, initial={"fecha": date.today()})
        mensaje = request.session.pop("aviso_mov", None)

    cob = indicadores.cobertura_categorizacion(u)
    lista = (
        Movimiento.objects.filter(usuario=u)
        .select_related("categoria")[:60]
    )
    return render(
        request,
        "finanzas/movimientos.html",
        {
            "form": form,
            "mensaje": mensaje,
            "movimientos": lista,
            "cobertura": cob,
            "pct_cobertura": None if cob is None else round(cob * 100, 1),
        },
    )


# --------------------------------------------------------------- importación
@login_required
def importar(request):
    """Importación de movimientos desde archivos CSV y XLSX.

    Flujo en tres pasos: análisis del archivo con mapeo propuesto, corrección
    opcional del mapeo por parte del usuario, y confirmación de los
    movimientos seleccionados.
    """
    from . import importador

    ctx = {"formatos": LoteImportacion.FORMATOS,
           "lotes": LoteImportacion.objects.filter(usuario=request.user)[:8]}

    def previsualizar(nombre, enc, filas, mapeo):
        cands, desc = importador.extraer(enc, filas, mapeo)
        cands = importador.marcar_duplicados(request.user, cands)
        request.session["import_prev"] = {
            "nombre": nombre,
            "formato": "xlsx" if nombre.lower().endswith((".xlsx", ".xlsm")) else "csv",
            "detectados": len(cands) + desc,
            "candidatos": [{**c, "fecha": c["fecha"].isoformat(), "monto": str(c["monto"])}
                           for c in cands],
        }
        campos = [(c, mapeo.get(c)) for c in importador.CAMPOS]
        ctx.update({"previsualizacion": cands, "encabezados": list(enumerate(enc)),
                    "campos_mapeo": campos, "descartados": desc, "nombre": nombre,
                    "nuevos": sum(1 for c in cands if not c["duplicado"])})

    if request.method == "POST" and request.POST.get("paso") == "confirmar":
        datos = request.session.get("import_prev")
        if not datos:
            return redirect("importar")
        acept = [c for i, c in enumerate(datos["candidatos"])
                 if str(i) in request.POST.getlist("aceptar")]
        for c in acept:
            c["fecha"] = date.fromisoformat(c["fecha"])
            c["monto"] = Decimal(c["monto"])
        lote, n = importador.confirmar(
            request.user, datos["nombre"], datos["formato"],
            request.POST.get("institucion", ""), acept, datos["detectados"])
        request.session.pop("import_prev", None)
        request.session.pop("import_raw", None)
        ctx["mensaje"] = (f"Se importaron {n} movimientos desde {lote.nombre_archivo}. "
                          f"Lote registrado con {lote.registros_detectados} registros detectados.")
        ctx["lotes"] = LoteImportacion.objects.filter(usuario=request.user)[:8]
        return render(request, "finanzas/importar.html", ctx)

    if request.method == "POST" and request.POST.get("paso") == "remapear":
        raw = request.session.get("import_raw")
        if not raw:
            return redirect("importar")
        mapeo = importador.mapeo_desde_formulario(request.POST, len(raw["encabezados"]))
        previsualizar(raw["nombre"], raw["encabezados"], raw["filas"], mapeo)
        ctx["mensaje"] = "Mapeo actualizado. Revisa los movimientos antes de confirmar."
        return render(request, "finanzas/importar.html", ctx)

    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        try:
            enc, filas = importador.leer_tabla(f.name, f.read())
            filas = importador.filas_serializables(filas)
            mapeo = importador.proponer_mapeo(enc)
        except Exception as e:
            ctx["error"] = f"No fue posible leer el archivo: {e}"
            return render(request, "finanzas/importar.html", ctx)
        # La tabla se conserva en la sesión solo mientras dura la revisión;
        # el archivo original no se almacena (RNF04).
        request.session["import_raw"] = {"nombre": f.name, "encabezados": enc, "filas": filas[:5000]}
        previsualizar(f.name, enc, filas, mapeo)
    return render(request, "finanzas/importar.html", ctx)


# --------------------------------------------------------------- reportes
@login_required
def reportes(request):
    """Reportes financieros exportables en PDF, XLSX y CSV (RF13)."""
    from . import reportes as rep

    anio, mes = _periodo(request)
    formato = request.GET.get("formato")
    if formato in ("pdf", "xlsx", "csv"):
        d = rep.datos_reporte(request.user, anio, mes)
        contenido, tipo = {
            "pdf": (rep.a_pdf, "application/pdf"),
            "xlsx": (rep.a_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "csv": (rep.a_csv, "text/csv; charset=utf-8"),
        }[formato]
        r = HttpResponse(contenido(d), content_type=tipo)
        r["Content-Disposition"] = f'attachment; filename="reporte_{anio}_{mes:02d}.{formato}"'
        return r

    d = rep.datos_reporte(request.user, anio, mes)
    meses_disponibles = (Movimiento.objects.filter(usuario=request.user)
                         .dates("fecha", "month", order="DESC"))
    return render(request, "finanzas/reportes.html", {
        "d": d, "anio": anio, "mes": mes,
        "resumen": rep.resumen_filas(d),
        "periodos": [(p.year, p.month, rep.etiqueta_periodo(p.year, p.month)) for p in meses_disponibles],
    })


# ------------------------------------------------------------------ asistente
@login_required
def asistente(request):
    """Asistente conversacional basado en NLU."""
    from .asistente import responder, INTENCIONES

    historial = request.session.get("chat", [])
    if request.method == "POST":
        texto = (request.POST.get("consulta") or "").strip()
        if texto:
            r = responder(request.user, texto)
            historial.append({"usuario": texto, "sistema": r["respuesta"],
                              "intencion": r["intencion"], "entidades": r["entidades"],
                              "resuelta": r["resuelta"]})
            request.session["chat"] = historial[-12:]
        return redirect("asistente")

    resueltas = ConsultaAsistente.objects.filter(usuario=request.user, resuelta=True).count()
    total = ConsultaAsistente.objects.filter(usuario=request.user).count()
    return render(request, "finanzas/asistente.html", {
        "historial": historial,
        "ejemplos": [i["ejemplo"] for i in INTENCIONES],
        "intenciones": len(INTENCIONES),
        "cobertura": round(resueltas / total * 100, 1) if total else None,
        "total_consultas": total,
    })
