# Sistema Inteligente de Gestión Financiera Personal (SIGFP)

Prototipo académico del Trabajo Terminal de la Maestría en Gestión de
Tecnologías de la Información y Comunicación, Facultad de Ciencias
Administrativas, Universidad Autónoma de Baja California.

**Autora:** Elena Guadalupe Gutiérrez Escobar
**Directora de Trabajo Terminal:** Dra. Guadalupe Abigail Arreguín Silva

---

## Estado de la versión

Siete de los ocho módulos previstos están implementados (87.5 %).

| Módulo | Estado |
|---|---|
| Modelo de datos en PostgreSQL (siete entidades) | Implementado |
| Registro manual de ingresos y egresos, con validación en servidor | Implementado |
| Categorización automatizada por reglas, con categoría de respaldo | Implementado |
| Tablero de indicadores (once indicadores) | Implementado |
| Importación de CSV y XLSX con mapeo editable, revisión y deduplicación | Implementado |
| Asistente conversacional con comprensión de lenguaje natural (spaCy, sin modelos de lenguaje de gran escala) | Implementado |
| Reportes exportables en PDF, XLSX y CSV | Implementado |
| Extracción desde estados de cuenta en PDF (dos instituciones) | Pendiente |

---

## Requisitos

- Python 3.11 o superior
- PostgreSQL 14 o superior

## Instalación local

```sql
CREATE USER sigfp WITH PASSWORD 'sigfp2026' CREATEDB;
CREATE DATABASE sigfp_db OWNER sigfp ENCODING 'UTF8';
```

```bash
python -m venv venv
source venv/bin/activate          # En Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download es_core_news_sm
python manage.py migrate
python manage.py cargar_demo      # datos sintéticos de demostración
python manage.py runserver
```

Acceder en `http://127.0.0.1:8000/` con usuario `demo` y contraseña `demo2026`.

El comando `cargar_demo` genera de forma determinista 225 movimientos
ficticios en seis meses, nueve categorías, catorce reglas, cinco presupuestos
y dos metas de ahorro. Los datos no corresponden a ninguna persona real.

## Pruebas

```bash
python manage.py test finanzas            # 19 pruebas automatizadas
python manage.py evaluar_asistente        # corpus fijo del asistente
```

El corpus del asistente (doce consultas del dominio y cuatro ajenas a él) está
fijado en `finanzas/tests.py`, de modo que la prueba técnica de
reconocimiento de intenciones es reproducible.

## Configuración por variables de entorno

En producción la configuración se toma de variables de entorno; si no
existen, se usan los valores de desarrollo local.

| Variable | Uso |
|---|---|
| `DATABASE_URL` | Cadena de conexión a PostgreSQL |
| `SECRET_KEY` | Clave secreta de Django |
| `DEBUG` | `0` en producción |
| `ALLOWED_HOSTS` | Dominios permitidos, separados por comas |

El archivo `render.yaml` describe el despliegue en Render.

## Estructura

```
config/                 configuración del proyecto Django
finanzas/
  models.py             siete entidades del dominio
  forms.py              validación de la captura manual
  categorizador.py      motor de reglas y categorías de respaldo
  importador.py         lectura, mapeo, deduplicación y confirmación
  indicadores.py        once indicadores de inteligencia de negocios
  asistente.py          comprensión de lenguaje natural por intenciones
  reportes.py           reportes en PDF, XLSX y CSV
  tests.py              pruebas automatizadas y corpus del asistente
  management/commands/  cargar_demo, evaluar_asistente
templates/              plantillas de las vistas
ejemplos/               archivo CSV de ejemplo para la importación
```
