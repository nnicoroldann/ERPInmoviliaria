"""
routers/boletas.py

Permite que el inquilino suba el comprobante (foto o PDF) de su boleta
de gas o agua desde su portal, en dos pasos:

1. POST /mis-boletas/leer: sube el archivo. Se guarda en una carpeta
   privada (Web/uploads_privados/comprobantes/, que NO se sirve como
   estática) y se intenta leer el monto y el vencimiento
   automáticamente (ocr_boletas.py). Se muestra un formulario de
   confirmación con esos valores ya cargados -o vacíos, si no se pudo
   leer nada- para que el inquilino los revise ANTES de guardar nada.

2. POST /mis-boletas/confirmar: recién acá se guarda (o se completa)
   la fila en facturas_gas / facturas_agua, con los valores que el
   inquilino confirmó, vinculada al archivo subido.

GET /mis-boletas/comprobante/{tipo}/{factura_id} sirve ese archivo:
solo puede verlo el inquilino dueño de esa unidad, o el personal de la
inmobiliaria (admin/usuario).
"""

import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from database import get_connection
from deps import get_current_user, templates, verify_csrf
from ocr_boletas import adivinar_campos, extraer_texto

router = APIRouter(prefix="/mis-boletas", tags=["boletas"])

COMPROBANTES_DIR = Path(__file__).resolve().parent.parent / "uploads_privados" / "comprobantes"
COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 8 * 1024 * 1024  # 8 MB
TIPOS_PERMITIDOS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}
TABLA_POR_TIPO = {"gas": "facturas_gas", "agua": "facturas_agua"}
ETIQUETA_POR_TIPO = {"gas": "Gas", "agua": "Agua"}
NOMBRE_ARCHIVO_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|jpg|png)$")


def _contrato_del_inquilino(conn, user: dict, contrato_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT co.*, un.tiene_gas
            FROM contratos co
            JOIN unidades un ON un.id = co.unidad_id
            WHERE co.id = %s AND co.cliente_id = %s;
            """,
            (contrato_id, user.get("cliente_id")),
        )
        return cur.fetchone()


@router.get("/nueva")
def form_nueva(request: Request, tipo: str, contrato_id: int, user: dict = Depends(get_current_user)):
    if user.get("rol") != "inquilino" or tipo not in TABLA_POR_TIPO:
        return RedirectResponse("/?error=Acción no disponible", status_code=303)

    conn = get_connection()
    try:
        contrato = _contrato_del_inquilino(conn, user, contrato_id)
    finally:
        conn.close()
    if not contrato:
        return RedirectResponse("/?error=Ese contrato no pertenece a tu cuenta", status_code=303)
    if tipo == "gas" and not contrato["tiene_gas"]:
        return RedirectResponse("/?error=Esa unidad no tiene gas", status_code=303)

    return templates.TemplateResponse("boleta_subir.html", {
        "request": request,
        "tipo": tipo,
        "etiqueta": ETIQUETA_POR_TIPO[tipo],
        "contrato_id": contrato_id,
    })


@router.post("/leer")
async def leer(
    request: Request,
    tipo: str = Form(...),
    contrato_id: int = Form(...),
    archivo: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    if user.get("rol") != "inquilino" or tipo not in TABLA_POR_TIPO:
        return RedirectResponse("/?error=Acción no disponible", status_code=303)

    conn = get_connection()
    try:
        contrato = _contrato_del_inquilino(conn, user, contrato_id)
    finally:
        conn.close()
    if not contrato:
        return RedirectResponse("/?error=Ese contrato no pertenece a tu cuenta", status_code=303)

    def _con_error(mensaje: str, status_code: int = 400):
        return templates.TemplateResponse("boleta_subir.html", {
            "request": request, "tipo": tipo, "etiqueta": ETIQUETA_POR_TIPO[tipo],
            "contrato_id": contrato_id, "error": mensaje,
        }, status_code=status_code)

    if archivo is None or not archivo.filename:
        return _con_error("Elegí un archivo para subir.")

    extension = TIPOS_PERMITIDOS.get(archivo.content_type)
    if not extension:
        return _con_error("Solo se aceptan archivos PDF, JPG o PNG.")

    contenido = await archivo.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        return _con_error("El archivo es demasiado grande (máximo 8 MB).")

    nombre_archivo = f"{secrets.token_hex(16)}.{extension}"
    (COMPROBANTES_DIR / nombre_archivo).write_bytes(contenido)

    texto = extraer_texto(str(COMPROBANTES_DIR / nombre_archivo), archivo.content_type)
    campos = adivinar_campos(texto)

    return templates.TemplateResponse("boleta_confirmar.html", {
        "request": request,
        "tipo": tipo,
        "etiqueta": ETIQUETA_POR_TIPO[tipo],
        "contrato_id": contrato_id,
        "archivo_temp": nombre_archivo,
        "monto": campos["monto"],
        "vencimiento": campos["vencimiento"].isoformat() if campos["vencimiento"] else "",
        "se_pudo_leer": bool(texto.strip()),
    })


@router.post("/confirmar")
def confirmar(
    tipo: str = Form(...),
    contrato_id: int = Form(...),
    archivo_temp: str = Form(...),
    periodo: str = Form(...),
    monto: float = Form(...),
    vencimiento: str = Form(""),
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    if user.get("rol") != "inquilino" or tipo not in TABLA_POR_TIPO:
        return RedirectResponse("/?error=Acción no disponible", status_code=303)
    if not NOMBRE_ARCHIVO_RE.match(archivo_temp):
        return RedirectResponse("/?error=Archivo inválido", status_code=303)
    if not (COMPROBANTES_DIR / archivo_temp).exists():
        return RedirectResponse(
            "/?error=El archivo subido ya no está disponible, subilo de nuevo", status_code=303
        )

    conn = get_connection()
    try:
        contrato = _contrato_del_inquilino(conn, user, contrato_id)
        if not contrato:
            return RedirectResponse("/?error=Ese contrato no pertenece a tu cuenta", status_code=303)

        tabla = TABLA_POR_TIPO[tipo]
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id FROM {tabla} WHERE unidad_id = %s AND periodo = %s;",
                (contrato["unidad_id"], periodo),
            )
            existente = cur.fetchone()

            if existente:
                cur.execute(
                    f"UPDATE {tabla} SET comprobante_path = %s, subido_por = 'inquilino' WHERE id = %s;",
                    (archivo_temp, existente["id"]),
                )
                mensaje = "ok=Comprobante adjuntado a la factura existente de ese período"
            else:
                cur.execute(
                    f"""
                    INSERT INTO {tabla} (unidad_id, periodo, monto, estado, vencimiento, comprobante_path, subido_por)
                    VALUES (%s, %s, %s, 'pendiente', %s, %s, 'inquilino');
                    """,
                    (contrato["unidad_id"], periodo, monto, vencimiento or None, archivo_temp),
                )
                mensaje = "ok=Boleta cargada con éxito"
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(f"/?{mensaje}", status_code=303)


@router.get("/comprobante/{tipo}/{factura_id}")
def ver_comprobante(tipo: str, factura_id: int, user: dict = Depends(get_current_user)):
    if tipo not in TABLA_POR_TIPO:
        raise HTTPException(status_code=404)
    tabla = TABLA_POR_TIPO[tipo]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {tabla} WHERE id = %s;", (factura_id,))
            factura = cur.fetchone()

        if not factura or not factura["comprobante_path"]:
            raise HTTPException(status_code=404)

        es_personal = user.get("rol") in ("admin", "usuario")
        es_su_unidad = False
        if user.get("rol") == "inquilino" and user.get("cliente_id"):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM contratos WHERE unidad_id = %s AND cliente_id = %s LIMIT 1;",
                    (factura["unidad_id"], user.get("cliente_id")),
                )
                es_su_unidad = cur.fetchone() is not None
    finally:
        conn.close()

    if not (es_personal or es_su_unidad):
        raise HTTPException(status_code=403)

    ruta = COMPROBANTES_DIR / factura["comprobante_path"]
    if not ruta.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(ruta))
