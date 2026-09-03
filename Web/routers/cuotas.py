"""
routers/cuotas.py

CRUD completo de la tabla cuotas. El campo contrato_id se muestra
como select, cargado dinámicamente desde la tabla contratos.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import get_current_user, require_admin, templates, verify_csrf

router = APIRouter(prefix="/cuotas", tags=["cuotas"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "contrato_id", "label": "Contrato (ID)"},
    {"key": "mes", "label": "Mes"},
    {"key": "monto", "label": "Monto"},
    {"key": "estado", "label": "Estado"},
    {"key": "fecha_pago", "label": "Fecha de pago"},
]

ESTADOS = [
    {"value": "pendiente", "label": "Pendiente"},
    {"value": "pagado", "label": "Pagado"},
    {"value": "vencido", "label": "Vencido"},
    {"value": "parcial", "label": "Parcial"},
]


def _opciones_contratos(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, cl.nombre, cl.apellido, u.direccion
            FROM contratos c
            JOIN clientes cl ON cl.id = c.cliente_id
            JOIN unidades u ON u.id = c.unidad_id
            ORDER BY c.id;
            """
        )
        filas = cur.fetchall()
    return [
        {"value": f["id"], "label": f"{f['id']} - {f['nombre']} {f['apellido']} / {f['direccion']}"}
        for f in filas
    ]


def _campos(conn):
    return [
        {"name": "contrato_id", "label": "Contrato", "type": "select", "required": True,
         "options": _opciones_contratos(conn)},
        {"name": "mes", "label": "Mes (formato YYYY-MM)", "type": "text", "required": True,
         "help": "Ej: 2026-03"},
        {"name": "monto", "label": "Monto", "type": "number", "step": "0.01", "required": True},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
        {"name": "fecha_pago", "label": "Fecha de pago", "type": "date", "required": False},
        {"name": "comprobante", "label": "Comprobante", "type": "text", "required": False},
    ]


@router.get("")
def listar(request: Request, user: dict = Depends(get_current_user)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cuotas ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Cuotas",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/cuotas",
        "add_url": "/cuotas/nuevo",
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
        "title": "Nueva cuota",
        "fields": fields,
        "values": {},
        "back_url": "/cuotas",
    })


@router.post("/nuevo")
def crear(
    contrato_id: int = Form(...),
    mes: str = Form(...),
    monto: float = Form(...),
    estado: str = Form("pendiente"),
    fecha_pago: str = Form(""),
    comprobante: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cuotas (contrato_id, mes, monto, estado, fecha_pago, comprobante)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (contrato_id, mes, monto, estado, fecha_pago or None, comprobante or None),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/cuotas/nuevo?error=Ya existe una cuota para ese contrato en ese mes", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/cuotas?ok=Cuota creada con éxito", status_code=303)


@router.get("/{cuota_id}/editar")
def form_editar(request: Request, cuota_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cuotas WHERE id = %s;", (cuota_id,))
            cuota = cur.fetchone()
        fields = _campos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar cuota #{cuota_id}",
        "fields": fields,
        "values": cuota or {},
        "back_url": "/cuotas",
    })


@router.post("/{cuota_id}/editar")
def editar(
    cuota_id: int,
    contrato_id: int = Form(...),
    mes: str = Form(...),
    monto: float = Form(...),
    estado: str = Form("pendiente"),
    fecha_pago: str = Form(""),
    comprobante: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cuotas
                SET contrato_id=%s, mes=%s, monto=%s, estado=%s, fecha_pago=%s, comprobante=%s
                WHERE id=%s;
                """,
                (contrato_id, mes, monto, estado, fecha_pago or None, comprobante or None, cuota_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/cuotas/{cuota_id}/editar?error=Ya existe otra cuota para ese contrato en ese mes", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/cuotas?ok=Cuota actualizada", status_code=303)


@router.post("/{cuota_id}/eliminar")
def eliminar(cuota_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cuotas WHERE id = %s;", (cuota_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/cuotas?ok=Cuota eliminada", status_code=303)
