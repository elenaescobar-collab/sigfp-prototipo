from django.urls import path

from . import views

urlpatterns = [
    path("", views.tablero, name="tablero"),
    path("movimientos/", views.movimientos, name="movimientos"),
    path("importar/", views.importar, name="importar"),
    path("asistente/", views.asistente, name="asistente"),
    path("reportes/", views.reportes, name="reportes"),
]
