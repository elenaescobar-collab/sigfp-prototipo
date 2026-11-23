"""
Pruebas automatizadas del prototipo.

Se ejecutan con:  python manage.py test finanzas

Cubren los cuatro mecanismos centrales (categorización, importación,
asistente conversacional y reportes) y la validación de la captura manual.
El corpus del asistente se fija aquí para que la prueba de reconocimiento de
intenciones sea reproducible por un tercero.
"""

import io
import zipfile
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase

from . import categorizador, importador, reportes
from .asistente import responder
from .forms import MovimientoForm
from .models import (Categoria, ConsultaAsistente, LoteImportacion, MetaAhorro,
                     Movimiento, Presupuesto, ReglaCategorizacion)


class Base(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("prueba", password="clave-prueba-2026")
        mk = lambda n, t, nat="variable": Categoria.objects.create(usuario=self.u, nombre=n, tipo=t, naturaleza=nat)
        self.super = mk("Supermercado", "egreso")
        self.transp = mk("Transporte", "egreso")
        self.renta = mk("Renta", "egreso", "fijo")
        self.sueldo = mk("Sueldo", "ingreso")
        ReglaCategorizacion.objects.create(usuario=self.u, patron="walmart", categoria=self.super, prioridad=10)
        ReglaCategorizacion.objects.create(usuario=self.u, patron="uber", categoria=self.transp, prioridad=20)
        ReglaCategorizacion.objects.create(usuario=self.u, patron="nomina", categoria=self.sueldo, prioridad=5)

    def mov(self, desc, monto, fecha=date(2026, 10, 15), cat=None):
        return Movimiento.objects.create(usuario=self.u, fecha=fecha, descripcion=desc,
                                         monto=Decimal(monto), categoria=cat)


# ------------------------------------------------------------ categorización
class CategorizacionTests(Base):
    def test_regla_coincide_sin_distinguir_mayusculas(self):
        r = categorizador.sugerir_categoria(self.u, "COMPRA WALMART SUC 123")
        self.assertEqual(r.categoria, self.super)

    def test_sin_coincidencia_devuelve_none(self):
        self.assertIsNone(categorizador.sugerir_categoria(self.u, "Farmacia del centro"))

    def test_aplicar_marca_y_cuenta(self):
        m = self.mov("Viaje UBER aeropuerto", "180.00")
        self.assertTrue(categorizador.aplicar(self.u, m))
        m.refresh_from_db()
        self.assertEqual(m.categoria, self.transp)
        self.assertTrue(m.categorizado_automaticamente)
        self.assertEqual(ReglaCategorizacion.objects.get(patron="uber").veces_aplicada, 1)

    def test_categoria_del_usuario_prevalece(self):
        m = self.mov("Walmart regalo", "300.00", cat=self.renta)
        self.assertEqual(categorizador.clasificar_o_respaldar(self.u, m, False), "usuario")
        m.refresh_from_db()
        self.assertEqual(m.categoria, self.renta)

    def test_respaldo_conserva_sentido_y_no_infla_cobertura(self):
        m = self.mov("Depósito de un amigo", "500.00")
        self.assertEqual(categorizador.clasificar_o_respaldar(self.u, m, True), "respaldo")
        m.refresh_from_db()
        self.assertEqual(m.categoria.nombre, categorizador.GENERICA_INGRESO)
        self.assertEqual(m.categoria.tipo, Categoria.TIPO_INGRESO)
        self.assertFalse(m.categorizado_automaticamente)


# ---------------------------------------------------------------- importación
CSV_BANCO = (
    "Estado de cuenta\n"
    "Fecha;Concepto;Cargo;Abono\n"
    "01/10/2026;PAGO NOMINA UABC;;8,500.00\n"
    "03/10/2026;WALMART SUPERCENTER;1.234,50;\n"
    "05/10/2026;UBER TRIP;95.00;\n"
    "06/10/2026;Transferencia recibida Pérez;;300.00\n"
    "07/10/2026;Fila sin monto;;\n"
).encode("latin-1")


class ImportacionTests(Base):
    def leer(self):
        enc, filas = importador.leer_tabla("movimientos.csv", CSV_BANCO)
        return enc, importador.filas_serializables(filas)

    def test_lectura_latin1_y_punto_y_coma(self):
        enc, filas = self.leer()
        self.assertEqual(enc, ["Fecha", "Concepto", "Cargo", "Abono"])
        self.assertEqual(len(filas), 5)

    def test_mapeo_propuesto(self):
        enc, _ = self.leer()
        self.assertEqual(importador.proponer_mapeo(enc),
                         {"fecha": 0, "descripcion": 1, "cargo": 2, "abono": 3})

    def test_extraccion_montos_y_sentido(self):
        enc, filas = self.leer()
        cands, desc = importador.extraer(enc, filas, importador.proponer_mapeo(enc))
        self.assertEqual(desc, 1)
        self.assertEqual([c["monto"] for c in cands],
                         [Decimal("8500.00"), Decimal("1234.50"), Decimal("95.00"), Decimal("300.00")])
        self.assertEqual([c["es_ingreso"] for c in cands], [True, False, False, True])

    def test_mapeo_corregido_por_el_usuario(self):
        m = importador.mapeo_desde_formulario(
            {"map_fecha": "0", "map_descripcion": "1", "map_monto": "3", "map_cargo": "", "map_abono": "9"}, 4)
        self.assertEqual(m, {"fecha": 0, "descripcion": 1, "monto": 3})

    def test_duplicados_y_confirmacion(self):
        enc, filas = self.leer()
        cands, desc = importador.extraer(enc, filas, importador.proponer_mapeo(enc))
        lote, n = importador.confirmar(self.u, "movimientos.csv", "csv", "Banco de prueba", cands, len(cands) + desc)
        self.assertEqual(n, 4)
        self.assertEqual(lote.registros_detectados, 5)
        self.assertAlmostEqual(lote.tasa_extraccion, 0.8)
        # Clasificación: tres por regla y uno por respaldo de ingreso.
        sin_regla = Movimiento.objects.get(descripcion__startswith="Transferencia")
        self.assertEqual(sin_regla.categoria.nombre, categorizador.GENERICA_INGRESO)
        self.assertEqual(Movimiento.objects.filter(categorizado_automaticamente=True).count(), 3)
        # Reimportar el mismo archivo marca todo como duplicado.
        cands2, _ = importador.extraer(enc, filas, importador.proponer_mapeo(enc))
        cands2 = importador.marcar_duplicados(self.u, cands2)
        self.assertTrue(all(c["duplicado"] for c in cands2))


# ---------------------------------------------------- validación de captura
class FormularioTests(Base):
    def datos(self, monto):
        return {"fecha": "2026-10-20", "descripcion": "Prueba", "monto": monto, "sentido": "egreso"}

    def test_monto_negativo_o_cero_rechazado(self):
        for monto in ("-5", "0", "0.00"):
            self.assertFalse(MovimientoForm(self.datos(monto), usuario=self.u).is_valid(), monto)

    def test_monto_valido_aceptado(self):
        self.assertTrue(MovimientoForm(self.datos("0.01"), usuario=self.u).is_valid())

    def test_categoria_de_otro_usuario_rechazada(self):
        otro = User.objects.create_user("otro", password="x")
        ajena = Categoria.objects.create(usuario=otro, nombre="Ajena", tipo="egreso")
        f = MovimientoForm({**self.datos("10"), "categoria": ajena.id}, usuario=self.u)
        self.assertFalse(f.is_valid())


# -------------------------------------------------------------------- asistente
# Corpus fijo de la prueba técnica del reconocimiento de intenciones.
CONSULTAS_DOMINIO = [
    ("¿Cuánto gasté este mes?", "gasto_total"),
    ("¿Cuánto gasté en supermercado?", "gasto_por_categoria"),
    ("¿En qué categoría gasté más?", "categoria_mayor"),
    ("¿Cuánto gané este mes?", "ingreso_total"),
    ("¿Cuánto ahorré este mes?", "ahorro"),
    ("¿Gasté más que el mes pasado?", "comparar_periodos"),
    ("¿Voy bien con mi presupuesto?", "estado_presupuesto"),
    ("¿Cómo va mi meta de ahorro?", "avance_metas"),
    ("¿Cuánto gasté en transporte en octubre?", "gasto_por_categoria"),
    ("¿Cuál fue mi ingreso total de septiembre?", "ingreso_total"),
    ("¿Cuál es mi tasa de ahorro?", "ahorro"),
    ("¿Excedí algún presupuesto?", "estado_presupuesto"),
]
CONSULTAS_FUERA_DE_DOMINIO = [
    "¿Qué clima hará mañana?",
    "Préstame dinero",
    "Cuéntame un chiste",
    "¿Quién ganó el partido?",
]


def evaluar_corpus(usuario):
    """Devuelve los resultados del corpus; lo usa también el comando
    `evaluar_asistente` para reportar las cifras del capítulo de resultados."""
    dominio = [(q, esp, responder(usuario, q)["intencion"]) for q, esp in CONSULTAS_DOMINIO]
    fuera = [(q, responder(usuario, q)["intencion"]) for q in CONSULTAS_FUERA_DE_DOMINIO]
    return dominio, fuera


class AsistenteTests(Base):
    def setUp(self):
        super().setUp()
        self.mov("WALMART", "500.00", date(2026, 10, 3), self.super)
        self.mov("NOMINA", "8000.00", date(2026, 10, 1), self.sueldo)
        Presupuesto.objects.create(usuario=self.u, categoria=self.super, anio=2026, mes=10, monto_limite=400)
        MetaAhorro.objects.create(usuario=self.u, nombre="Laptop", monto_objetivo=1000,
                                  monto_acumulado=250, fecha_objetivo=date(2026, 12, 31))

    def test_consultas_del_dominio(self):
        dominio, _ = evaluar_corpus(self.u)
        fallas = [(q, esp, obt) for q, esp, obt in dominio if esp != obt]
        self.assertEqual(fallas, [], f"Consultas mal clasificadas: {fallas}")

    def test_consultas_fuera_del_dominio(self):
        _, fuera = evaluar_corpus(self.u)
        falsos_positivos = [(q, i) for q, i in fuera if i is not None]
        self.assertEqual(falsos_positivos, [], f"Falsos positivos: {falsos_positivos}")

    def test_bitacora_de_consultas(self):
        responder(self.u, "¿Cuánto gasté este mes?")
        responder(self.u, "Cuéntame un chiste")
        self.assertEqual(ConsultaAsistente.objects.filter(usuario=self.u, resuelta=True).count(), 1)
        self.assertEqual(ConsultaAsistente.objects.filter(usuario=self.u, resuelta=False).count(), 1)


# --------------------------------------------------------------------- reportes
class ReportesTests(Base):
    def setUp(self):
        super().setUp()
        self.mov("WALMART", "500.00", date(2026, 10, 3), self.super)
        self.mov("NOMINA", "8000.00", date(2026, 10, 1), self.sueldo)
        self.d = reportes.datos_reporte(self.u, 2026, 10)

    def test_cifras_coinciden_con_indicadores(self):
        self.assertEqual(self.d["ingresos"], Decimal("8000.00"))
        self.assertEqual(self.d["egresos"], Decimal("500.00"))
        self.assertEqual(self.d["balance"], Decimal("7500.00"))

    def test_formatos(self):
        self.assertTrue(reportes.a_pdf(self.d).startswith(b"%PDF"))
        with zipfile.ZipFile(io.BytesIO(reportes.a_xlsx(self.d))) as z:
            self.assertIn("xl/workbook.xml", z.namelist())
        csv_txt = reportes.a_csv(self.d).decode("utf-8-sig")
        self.assertTrue(csv_txt.startswith("fecha,descripcion,categoria,tipo,monto,origen"))
        self.assertEqual(len(csv_txt.strip().splitlines()), 3)

    def test_vista_requiere_sesion_y_descarga(self):
        c = Client()
        self.assertEqual(c.get("/reportes/").status_code, 302)
        c.force_login(self.u)
        r = c.get("/reportes/?anio=2026&mes=10&formato=xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
