"""Ejecuta el corpus fijo de la prueba técnica del asistente y reporta los
resultados. Uso: python manage.py evaluar_asistente --usuario demo"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from finanzas.asistente import UMBRAL
from finanzas.tests import CONSULTAS_DOMINIO, CONSULTAS_FUERA_DE_DOMINIO, evaluar_corpus


class Command(BaseCommand):
    help = "Evalúa el reconocimiento de intenciones con el corpus fijo de pruebas."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="demo")

    def handle(self, *args, **opts):
        u = User.objects.get(username=opts["usuario"])
        dominio, fuera = evaluar_corpus(u)
        aciertos = sum(1 for _, esp, obt in dominio if esp == obt)
        rechazos = sum(1 for _, obt in fuera if obt is None)
        self.stdout.write(f"Umbral de confianza: {UMBRAL}")
        self.stdout.write("\nConsultas del dominio")
        for q, esp, obt in dominio:
            self.stdout.write(f"  {'OK ' if esp == obt else 'ERR'}  {q}  →  {obt}  (esperada: {esp})")
        self.stdout.write("\nConsultas fuera del dominio (se espera rechazo)")
        for q, obt in fuera:
            self.stdout.write(f"  {'OK ' if obt is None else 'FP '}  {q}  →  {obt or 'rechazada'}")
        self.stdout.write(f"\nReconocidas correctamente: {aciertos} de {len(CONSULTAS_DOMINIO)}")
        self.stdout.write(f"Rechazadas correctamente: {rechazos} de {len(CONSULTAS_FUERA_DE_DOMINIO)}")
        self.stdout.write(f"Falsos positivos: {len(CONSULTAS_FUERA_DE_DOMINIO) - rechazos} de {len(CONSULTAS_FUERA_DE_DOMINIO)}")
