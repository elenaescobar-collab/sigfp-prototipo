"""
Carga un conjunto de datos ficticios para demostrar el prototipo.

Los datos NO corresponden a ninguna persona real: son sintéticos y se generan
de forma determinista para que la demostración sea reproducible. No deben
emplearse como resultados de la investigación.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from finanzas.categorizador import clasificar_o_respaldar
from finanzas.models import (
    ConsultaAsistente,
    Categoria,
    LoteImportacion,
    MetaAhorro,
    Movimiento,
    Presupuesto,
    ReglaCategorizacion,
)

CATEGORIAS = [
    ("Sueldo", "ingreso", "fijo", "#1d7a52"),
    ("Trabajo independiente", "ingreso", "variable", "#2f9e6e"),
    ("Renta", "egreso", "fijo", "#1f4e79"),
    ("Servicios", "egreso", "fijo", "#2d6ea8"),
    ("Supermercado", "egreso", "variable", "#a8322b"),
    ("Transporte", "egreso", "variable", "#c2683a"),
    ("Restaurantes", "egreso", "variable", "#b3892d"),
    ("Salud", "egreso", "variable", "#6b4fa0"),
    ("Entretenimiento", "egreso", "variable", "#9b4b77"),
]

REGLAS = [
    ("cfe", "Servicios", 10),
    ("telmex", "Servicios", 10),
    ("agua", "Servicios", 15),
    ("renta", "Renta", 10),
    ("soriana", "Supermercado", 20),
    ("calimax", "Supermercado", 20),
    ("oxxo", "Supermercado", 30),
    ("uber", "Transporte", 20),
    ("gasolina", "Transporte", 20),
    ("farmacia", "Salud", 20),
    ("cinepolis", "Entretenimiento", 20),
    ("netflix", "Entretenimiento", 20),
    ("nomina", "Sueldo", 5),
    ("sueldo", "Sueldo", 5),
]

PLANTILLAS = [
    ("Pago de luz CFE", "40-180", 1),
    ("Recibo Telmex internet", "60-70", 1),
    ("Pago de agua", "20-40", 1),
    ("Pago de renta departamento", "750-750", 1),
    ("Compra Soriana despensa", "35-160", 4),
    ("Compra Calimax", "25-90", 3),
    ("Oxxo artículos varios", "5-25", 6),
    ("Viaje Uber centro", "6-18", 5),
    ("Carga de gasolina", "35-60", 3),
    ("Farmacia Guadalajara", "10-70", 2),
    ("Cinepolis función", "12-24", 1),
    ("Suscripción Netflix", "15-15", 1),
    ("Café y comida corrida", "8-30", 6),
]


class Command(BaseCommand):
    help = "Carga datos ficticios de demostración del prototipo."

    def handle(self, *args, **options):
        random.seed(20261109)

        usuario, creado = User.objects.get_or_create(
            username="demo",
            defaults={
                "first_name": "Usuario",
                "last_name": "de demostración",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        usuario.set_password("demo2026")
        usuario.save()

        Movimiento.objects.filter(usuario=usuario).delete()
        Presupuesto.objects.filter(usuario=usuario).delete()
        MetaAhorro.objects.filter(usuario=usuario).delete()
        ReglaCategorizacion.objects.filter(usuario=usuario).delete()
        Categoria.objects.filter(usuario=usuario).delete()
        LoteImportacion.objects.filter(usuario=usuario).delete()
        ConsultaAsistente.objects.filter(usuario=usuario).delete()

        cats = {}
        for nombre, tipo, nat, color in CATEGORIAS:
            cats[nombre] = Categoria.objects.create(
                usuario=usuario, nombre=nombre, tipo=tipo, naturaleza=nat, color=color
            )

        for patron, cat, prioridad in REGLAS:
            ReglaCategorizacion.objects.create(
                usuario=usuario, patron=patron, categoria=cats[cat], prioridad=prioridad
            )

        lote = LoteImportacion.objects.create(
            usuario=usuario,
            nombre_archivo="movimientos_septiembre.csv",
            formato=LoteImportacion.FORMATO_CSV,
            institucion="Banco de ejemplo",
            registros_detectados=42,
            registros_confirmados=40,
        )

        hoy = date.today()
        primero = date(hoy.year, hoy.month, 1)

        def tope(f):
            # Ningún movimiento queda con fecha posterior al día de la carga.
            return min(f, hoy)
        total_mov = 0

        for retro in range(6):
            anio = primero.year
            mes = primero.month - retro
            while mes <= 0:
                mes += 12
                anio -= 1
            inicio = date(anio, mes, 1)

            Movimiento.objects.create(
                usuario=usuario,
                fecha=inicio,
                descripcion="Deposito de nomina quincenal",
                monto=Decimal("1100.00"),
                categoria=cats["Sueldo"],
                origen=Movimiento.ORIGEN_MANUAL,
            )
            Movimiento.objects.create(
                usuario=usuario,
                fecha=tope(inicio + timedelta(days=14)),
                descripcion="Deposito de nomina quincenal",
                monto=Decimal("1100.00"),
                categoria=cats["Sueldo"],
                origen=Movimiento.ORIGEN_MANUAL,
            )
            total_mov += 2

            if retro % 2 == 0:
                Movimiento.objects.create(
                    usuario=usuario,
                    fecha=tope(inicio + timedelta(days=9)),
                    descripcion="Proyecto freelance diseño",
                    monto=Decimal(random.randint(180, 420)),
                    categoria=cats["Trabajo independiente"],
                    origen=Movimiento.ORIGEN_MANUAL,
                )
                total_mov += 1

            for desc, rango, veces in PLANTILLAS:
                lo, hi = (int(x) for x in rango.split("-"))
                for _ in range(veces):
                    dia = random.randint(1, 27)
                    if retro == 0:
                        # Mes en curso: se reparte entre el día 1 y el día de
                        # la carga, conservando la secuencia aleatoria.
                        dia = 1 + (dia - 1) % hoy.day
                    mov = Movimiento(
                        usuario=usuario,
                        fecha=inicio + timedelta(days=dia - 1),
                        descripcion=desc,
                        monto=Decimal(random.randint(lo, hi)),
                        origen=(
                            Movimiento.ORIGEN_ARCHIVO
                            if retro == 1 and random.random() < 0.5
                            else Movimiento.ORIGEN_MANUAL
                        ),
                    )
                    if mov.origen == Movimiento.ORIGEN_ARCHIVO:
                        mov.lote = lote
                    mov.save()
                    clasificar_o_respaldar(usuario, mov, False)
                    total_mov += 1

        limites = {
            "Supermercado": 420,
            "Transporte": 180,
            "Restaurantes": 150,
            "Entretenimiento": 90,
            "Servicios": 260,
        }
        for nombre, limite in limites.items():
            Presupuesto.objects.create(
                usuario=usuario,
                categoria=cats[nombre],
                anio=hoy.year,
                mes=hoy.month,
                monto_limite=Decimal(limite),
            )

        MetaAhorro.objects.create(
            usuario=usuario,
            nombre="Fondo de emergencia",
            monto_objetivo=Decimal("3000.00"),
            monto_acumulado=Decimal("1180.00"),
            fecha_objetivo=date(hoy.year + 1, 6, 30),
        )
        MetaAhorro.objects.create(
            usuario=usuario,
            nombre="Computadora para el posgrado",
            monto_objetivo=Decimal("1200.00"),
            monto_acumulado=Decimal("860.00"),
            fecha_objetivo=date(hoy.year, 12, 31),
        )

        sin_cat = Movimiento.objects.filter(
            usuario=usuario, categoria__tipo__isnull=False,
            categoria__nombre__in=["Otros egresos", "Otros ingresos"],
        ).count()
        auto = Movimiento.objects.filter(
            usuario=usuario, categorizado_automaticamente=True
        ).count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Datos ficticios cargados: {total_mov} movimientos, "
                f"{auto} categorizados automáticamente, {sin_cat} en categoría de respaldo. "
                f"Usuario: demo / demo2026"
            )
        )
