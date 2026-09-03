"""
routers/propietarios.py

CRUD completo de la tabla propietarios (dueños de las unidades).

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/propietarios", tags=["propietarios"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "nombre", "label": "Nombre"},
    {"key": "apellido", "label": "Apellido"},
    {"key": "dni_cuit", "label": "DNI/CUIT"},
    {"key": "telefono", "label": "Teléfono"},
    {"key": "email", "label": "Email"},
    {"key": "cbu_alias", "label": "CBU/Alias"},
    {"key": "estado", "label": "Estado"},
]

FIELDS = [
    {"name": "nombre", "label": "Nombre", "type": "text", "required": True, "placeholder": "Ej: Carlos"},
    {"name": "apellido", "label": "Apellido", "type": "text", "required": True, "placeholder": "Ej: Andreoni"},
    {"name": "dni_cuit", "label": "DNI/CUIT", "type": "text", "required": False, "placeholder": "Ej: 20-12345678-9"},
    {"name": "telefono", "label": "Teléfono", "type": "text", "required": False, "placeholder": "Ej: 11 5555-5555"},
    {"name": "email", "label": "Email", "type": "email", "required": False, "placeholder": "Ej: carlos.andreoni@email.com"},
    {"name": "cbu_alias", "label": "CBU o alias (para liquidarle el alquiler)", "type": "text", "required": False, "placeholder": "Ej: carlos.andreoni.mp"},
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
            cur.execute("SELECT * FROM propietarios ORDER BY apellido, nombre;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Propietarios",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/propietarios",
        "add_url": "/propietarios/nuevo",
    })


@router.get("/nuevo")
def form_nuevo(request: Request, user: dict = Depends(require_admin)):
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": "Nuevo propietario",
        "fields": FIELDS,
        "values": {},
        "back_url": "/propietarios",
    })


@router.post("/nuevo")
def crear(
    nombre: str = Form(...),
    apellido: str = Form(...),
    dni_cuit: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    cbu_alias: str = Form(""),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO propietarios (nombre, apellido, dni_cuit, telefono, email, cbu_alias, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (nombre, apellido, dni_cuit or None, telefono or None, email or None, cbu_alias or None, estado),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/propietarios/nuevo?error=Ya existe un propietario con ese DNI/CUIT o email", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/propietarios?ok=Propietario creado con éxito", status_code=303)


@router.get("/{propietario_id}/editar")
def form_editar(request: Request, propietario_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM propietarios WHERE id = %s;", (propietario_id,))
            propietario = cur.fetchone()
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar propietario #{propietario_id}",
        "fields": FIELDS,
        "values": propietario or {},
        "back_url": "/propietarios",
    })


@router.post("/{propietario_id}/editar")
def editar(
    propietario_id: int,
    nombre: str = Form(...),
    apellido: str = Form(...),
    dni_cuit: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    cbu_alias: str = Form(""),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE propietarios
                SET nombre=%s, apellido=%s, dni_cuit=%s, telefono=%s, email=%s, cbu_alias=%s, estado=%s
                WHERE id=%s;
                """,
                (nombre, apellido, dni_cuit or None, telefono or None, email or None, cbu_alias or None, estado, propietario_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/propietarios/{propietario_id}/editar?error=Ya existe otro propietario con ese DNI/CUIT o email", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/propietarios?ok=Propietario actualizado", status_code=303)


@router.post("/{propietario_id}/eliminar")
def eliminar(propietario_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM propietarios WHERE id = %s;", (propietario_id,))
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return RedirectResponse("/propietarios?error=No se puede eliminar: tiene unidades asignadas", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/propietarios?ok=Propietario eliminado", status_code=303)
