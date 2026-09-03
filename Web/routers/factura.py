"""
routers/facturas_gas.py

CRUD completo de la tabla facturas_gas. El campo unidad_id se
muestra como select, cargado dinámicamente desde la tabla unidades.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/facturas-gas", tags=["facturas_gas"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "unidad_id", "label": "Unidad (ID)"},
    {"key": "periodo", "label": "Período"},
    {"key": "monto", "label": "Monto"},
    {"key": "estado", "label": "Estado"},
    {"key": "vencimiento", "label": "Vencimiento"},
    {"key": "comprobante_path", "label": "Comprobante"},
]

ESTADOS = [
    {"value": "pendiente", "label": "Pendiente"},
    {"value": "pagado", "label": "Pagado"},
    {"value": "vencido", "label": "Vencido"},
]


def _opciones_unidades(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, tipo, direccion, tiene_gas FROM unidades ORDER BY id;")
        filas = cur.fetchall()
    return [
        {
            "value": f["id"],
            "label": f"{f['id']} - {f['tipo']} en {f['direccion']}" + ("" if f["tiene_gas"] else " (sin gas)"),
        }
        for f in filas
    ]


def _campos(conn):
    return [
        {"name": "unidad_id", "label": "Unidad", "type": "select", "required": True,
         "options": _opciones_unidades(conn)},
        {"name": "periodo", "label": "Período (formato YYYY-MM)", "type": "text", "required": True,
         "placeholder": "Ej: 2026-03", "help": "Formato YYYY-MM, ej: 2026-03"},
        {"name": "monto", "label": "Monto", "type": "number", "step": "0.01", "required": True, "placeholder": "Ej: 15000"},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
        {"name": "vencimiento", "label": "Fecha de vencimiento", "type": "date", "required": False},
        {"name": "pagado_en", "label": "Fecha en que se pagó", "type": "date", "required": False},
    ]


@router.get("")
def listar(request: Request, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM facturas_gas ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Facturas de gas",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/facturas-gas",
        "add_url": "/facturas-gas/nuevo",
        "tipo_factura": "gas",
    })


@router.get("/nuevo")
def form_nuevo(request: Request, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        fields = _campos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": "Nueva factura de gas",
        "fields": fields,
        "values": {},
        "back_url": "/facturas-gas",
    })


@router.post("/nuevo")
def crear(
    unidad_id: int = Form(...),
    periodo: str = Form(...),
    monto: float = Form(...),
    estado: str = Form("pendiente"),
    vencimiento: str = Form(""),
    pagado_en: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO facturas_gas (unidad_id, periodo, monto, estado, vencimiento, pagado_en)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (unidad_id, periodo, monto, estado, vencimiento or None, pagado_en or None),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/facturas-gas/nuevo?error=Ya existe una factura para esa unidad en ese período", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas?ok=Factura creada con éxito", status_code=303)


@router.get("/{factura_id}/editar")
def form_editar(request: Request, factura_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM facturas_gas WHERE id = %s;", (factura_id,))
            factura = cur.fetchone()
        fields = _campos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar factura #{factura_id}",
        "fields": fields,
        "values": factura or {},
        "back_url": "/facturas-gas",
    })


@router.post("/{factura_id}/editar")
def editar(
    factura_id: int,
    unidad_id: int = Form(...),
    periodo: str = Form(...),
    monto: float = Form(...),
    estado: str = Form("pendiente"),
    vencimiento: str = Form(""),
    pagado_en: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE facturas_gas
                SET unidad_id=%s, periodo=%s, monto=%s, estado=%s, vencimiento=%s, pagado_en=%s
                WHERE id=%s;
                """,
                (unidad_id, periodo, monto, estado, vencimiento or None, pagado_en or None, factura_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/facturas-gas/{factura_id}/editar?error=Ya existe otra factura para esa unidad en ese período", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas?ok=Factura actualizada", status_code=303)


@router.post("/{factura_id}/eliminar")
def eliminar(factura_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM facturas_gas WHERE id = %s;", (factura_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas?ok=Factura eliminada", status_code=303)
