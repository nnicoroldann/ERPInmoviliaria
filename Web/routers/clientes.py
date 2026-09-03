"""
routers/clientes.py

CRUD completo (Crear, Listar, Editar, Eliminar) de la tabla clientes.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/clientes", tags=["clientes"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "nombre", "label": "Nombre"},
    {"key": "apellido", "label": "Apellido"},
    {"key": "dni_cuit", "label": "DNI/CUIT"},
    {"key": "telefono", "label": "Teléfono"},
    {"key": "email", "label": "Email"},
    {"key": "estado", "label": "Estado"},
]

FIELDS = [
    {"name": "nombre", "label": "Nombre", "type": "text", "required": True, "placeholder": "Ej: Juan"},
    {"name": "apellido", "label": "Apellido", "type": "text", "required": True, "placeholder": "Ej: Pérez"},
    {"name": "dni_cuit", "label": "DNI/CUIT", "type": "text", "required": True, "placeholder": "Ej: 20-12345678-9"},
    {"name": "telefono", "label": "Teléfono", "type": "text", "required": False, "placeholder": "Ej: 11 5555-5555"},
    {"name": "email", "label": "Email", "type": "email", "required": False, "placeholder": "Ej: juan.perez@email.com"},
    {
        "name": "estado", "label": "Estado", "type": "select", "required": True,
        "options": [
            {"value": "activo", "label": "Activo"},
            {"value": "inactivo", "label": "Inactivo"},
        ],
    },
]


@router.get("")
def listar(request: Request, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Clientes",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/clientes",
        "add_url": "/clientes/nuevo",
    })


@router.get("/nuevo")
def form_nuevo(request: Request, user: dict = Depends(require_admin)):
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": "Nuevo cliente",
        "fields": FIELDS,
        "values": {},
        "back_url": "/clientes",
    })


@router.post("/nuevo")
def crear(
    nombre: str = Form(...),
    apellido: str = Form(...),
    dni_cuit: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clientes (nombre, apellido, dni_cuit, telefono, email, estado)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (nombre, apellido, dni_cuit, telefono or None, email or None, estado),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/clientes/nuevo?error=Ya existe un cliente con ese DNI/CUIT o email", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/clientes?ok=Cliente creado con éxito", status_code=303)


@router.get("/{cliente_id}/editar")
def form_editar(request: Request, cliente_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes WHERE id = %s;", (cliente_id,))
            cliente = cur.fetchone()
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar cliente #{cliente_id}",
        "fields": FIELDS,
        "values": cliente or {},
        "back_url": "/clientes",
    })


@router.post("/{cliente_id}/editar")
def editar(
    cliente_id: int,
    nombre: str = Form(...),
    apellido: str = Form(...),
    dni_cuit: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE clientes
                SET nombre=%s, apellido=%s, dni_cuit=%s, telefono=%s, email=%s, estado=%s
                WHERE id=%s;
                """,
                (nombre, apellido, dni_cuit, telefono or None, email or None, estado, cliente_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/clientes/{cliente_id}/editar?error=Ya existe otro cliente con ese DNI/CUIT o email", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/clientes?ok=Cliente actualizado", status_code=303)


@router.post("/{cliente_id}/eliminar")
def eliminar(cliente_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clientes WHERE id = %s;", (cliente_id,))
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return RedirectResponse("/clientes?error=No se puede eliminar: tiene contratos asociados", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/clientes?ok=Cliente eliminado", status_code=303)
