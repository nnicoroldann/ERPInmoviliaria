"""
routers/importar.py

Permite a un admin subir el Excel de control de la inmobiliaria y
cargar todos sus datos a la base, en dos pasos (mismo patrón que la
carga de boletas en boletas.py):

1. POST /importar/previsualizar: sube el .xlsx, arma el plan de
   importación (importador_excel.construir_plan) SIN escribir nada en
   la base, y muestra un resumen (cuántos clientes/propietarios/
   unidades/cuotas/facturas se van a cargar) más la lista de avisos
   (nombres que no se pudieron emparejar, datos que faltaban y se
   completaron con un placeholder, etc.) para que el admin lo revise
   antes de confirmar.

2. POST /importar/confirmar: vuelve a leer el mismo archivo temporal,
   arma el plan de nuevo (por las dudas de que algo haya cambiado en
   la base mientras tanto) y esta vez sí lo aplica
   (importador_excel.aplicar_plan) en una única transacción. Borra el
   archivo temporal al terminar, haya salido bien o mal.

Solo lo puede usar un admin (require_admin). El archivo subido se
guarda en una carpeta privada mientras dura la revisión — nunca queda
expuesto como estático ni se conserva una copia permanente del Excel.
"""

import re
import secrets
from pathlib import Path
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, templates, verify_csrf
from importador_excel import aplicar_plan, construir_plan

router = APIRouter(prefix="/importar", tags=["importar"])

EXCEL_TEMP_DIR = Path(__file__).resolve().parent.parent / "uploads_privados" / "excel_importar"
EXCEL_TEMP_DIR.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 20 * 1024 * 1024  # 20 MB
NOMBRE_ARCHIVO_RE = re.compile(r"^[a-f0-9]{32}\.xlsx$")


@router.get("")
def form_importar(request: Request, user: dict = Depends(require_admin)):
    return templates.TemplateResponse("importar.html", {"request": request})


@router.post("/previsualizar")
async def previsualizar(
    request: Request,
    archivo: Optional[UploadFile] = File(None),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    def _con_error(mensaje: str, status_code: int = 400):
        return templates.TemplateResponse("importar.html", {
            "request": request, "error": mensaje,
        }, status_code=status_code)

    if archivo is None or not archivo.filename:
        return _con_error("Elegí un archivo Excel (.xlsx) para subir.")
    if not archivo.filename.lower().endswith(".xlsx"):
        return _con_error("Solo se aceptan archivos .xlsx (Excel).")

    contenido = await archivo.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        return _con_error("El archivo es demasiado grande (máximo 20 MB).")

    nombre_archivo = f"{secrets.token_hex(16)}.xlsx"
    ruta = EXCEL_TEMP_DIR / nombre_archivo
    ruta.write_bytes(contenido)

    try:
        wb = openpyxl.load_workbook(str(ruta), data_only=True)
    except Exception:
        ruta.unlink(missing_ok=True)
        return _con_error("No se pudo leer el archivo. ¿Es un Excel (.xlsx) válido y no está dañado?")

    conn = get_connection()
    try:
        plan = construir_plan(wb, conn)
    except Exception as e:
        ruta.unlink(missing_ok=True)
        return _con_error(f"No se pudo leer el contenido del Excel: {e}")
    finally:
        conn.close()

    return templates.TemplateResponse("importar_confirmar.html", {
        "request": request,
        "archivo_temp": nombre_archivo,
        "nombre_original": archivo.filename,
        "resumen": plan["resumen"],
        "avisos": plan["avisos"],
    })


@router.post("/confirmar")
def confirmar(
    archivo_temp: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    if not NOMBRE_ARCHIVO_RE.match(archivo_temp):
        return RedirectResponse("/importar?error=Archivo inválido", status_code=303)
    ruta = EXCEL_TEMP_DIR / archivo_temp
    if not ruta.exists():
        return RedirectResponse(
            "/importar?error=El archivo ya no está disponible, subilo de nuevo", status_code=303
        )

    conn = get_connection()
    try:
        try:
            wb = openpyxl.load_workbook(str(ruta), data_only=True)
            plan = construir_plan(wb, conn)
            resultado = aplicar_plan(conn, plan)
        except Exception as e:
            conn.rollback()
            return RedirectResponse(f"/importar?error=No se pudo completar la importación: {e}", status_code=303)
    finally:
        conn.close()
        ruta.unlink(missing_ok=True)

    mensaje = (
        f"Importación completa: {resultado['clientes_creados']} clientes, "
        f"{resultado['propietarios_creados']} propietarios, {resultado['unidades_creadas']} unidades, "
        f"{resultado['contratos_creados']} contratos, {resultado['cuotas_creadas']} cuotas y "
        f"{resultado['facturas_gas_creadas']} facturas de gas nuevas "
        f"({resultado['telefonos_actualizados']} teléfonos completados)."
    )
    return RedirectResponse(f"/importar?ok={mensaje}", status_code=303)
