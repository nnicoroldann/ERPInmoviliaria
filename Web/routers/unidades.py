"""
routers/unidades.py

CRUD completo de la tabla unidades (mostradas en la web como
"Propiedades": son las propiedades registradas, cada una con su
propietario). El campo propietario_id se muestra como select, cargado
dinámicamente desde la tabla propietarios (puede quedar sin asignar).

El listado tiene una búsqueda por texto libre (parámetro ?q=) que
busca a la vez en id, tipo, dirección, identificador interno, N° de
cuenta de gas y nombre/apellido del propietario.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/unidades", tags=["unidades"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "tipo", "label": "Tipo"},
    {"key": "direccion", "label": "Dirección"},
    {"key": "identificador_interno", "label": "Identificador"},
    {"key": "propietario", "label": "Propietario"},
    {"key": "estado", "label": "Estado"},
    {"key": "tiene_gas", "label": "¿Tiene gas?"},
    {"key": "gas_cuenta", "label": "N° cuenta de gas"},
]

ESTADOS_UNIDAD = [
    {"value": "vacia", "label": "Vacía"},
    {"value": "ocupada", "label": "Ocupada"},
]

TIPOS_UNIDAD = [
    {"value": "casa", "label": "Casa"},
    {"value": "local", "label": "Local"},
    {"value": "cochera", "label": "Cochera"},
]


def _opciones_propietarios(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, nombre, apellido FROM propietarios ORDER BY apellido, nombre;")
        filas = cur.fetchall()
    opciones = [{"value": "", "label": "— Sin asignar —"}]
    opciones += [{"value": f["id"], "label": f"{f['apellido']} {f['nombre']}"} for f in filas]
    return opciones


def _campos(conn):
    return [
        {"name": "tipo", "label": "Tipo", "type": "select", "required": True, "options": TIPOS_UNIDAD},
        {"name": "direccion", "label": "Dirección", "type": "text", "required": True, "placeholder": "Ej: Av. Siempreviva 742"},
        {"name": "identificador_interno", "label": "Identificador interno", "type": "text", "required": False, "placeholder": "Ej: U-014"},
        {"name": "propietario_id", "label": "Propietario", "type": "select", "required": False,
         "options": _opciones_propietarios(conn)},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS_UNIDAD},
        {"name": "tiene_gas", "label": "¿Tiene gas?", "type": "checkbox", "required": False},
        {"name": "gas_cuenta", "label": "N° de cuenta de gas", "type": "text", "required": False, "placeholder": "Ej: 21060706"},
    ]


def _buscar_unidades(conn, q: str):
    q = (q or "").strip()
    base_select = """
        SELECT u.*,
               CASE WHEN p.id IS NULL THEN NULL ELSE p.apellido || ' ' || p.nombre END AS propietario
        FROM unidades u
        LEFT JOIN propietarios p ON p.id = u.propietario_id
    """
    with conn.cursor() as cur:
        if not q:
            cur.execute(base_select + " ORDER BY u.id;")
            return cur.fetchall()

        comodin = f"%{q}%"
        cur.execute(
            base_select + """
            WHERE u.id::text ILIKE %(q)s
               OR u.tipo ILIKE %(q)s
               OR u.direccion ILIKE %(q)s
               OR u.identificador_interno ILIKE %(q)s
               OR u.gas_cuenta ILIKE %(q)s
               OR p.nombre ILIKE %(q)s
               OR p.apellido ILIKE %(q)s
               OR (p.apellido || ' ' || p.nombre) ILIKE %(q)s
            ORDER BY u.id;
            """,
            {"q": comodin},
        )
        return cur.fetchall()


@router.get("")
def listar(request: Request, q: str = "", user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        rows = _buscar_unidades(conn, q)
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Propiedades",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/unidades",
        "add_url": "/unidades/nuevo",
        "search_url": "/unidades",
        "search_q": q,
        "search_placeholder": "Buscar por ID, tipo, dirección, identificador, N° de cuenta de gas o propietario...",
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
        "title": "Nueva propiedad",
        "fields": fields,
        "values": {},
        "back_url": "/unidades",
    })


@router.post("/nuevo")
def crear(
    tipo: str = Form(...),
    direccion: str = Form(...),
    identificador_interno: str = Form(""),
    propietario_id: str = Form(""),
    estado: str = Form("vacia"),
    tiene_gas: str = Form(None),
    gas_cuenta: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    propietario_id_val = int(propietario_id) if propietario_id else None
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unidades (tipo, direccion, identificador_interno, propietario_id, estado, tiene_gas, gas_cuenta)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (tipo, direccion, identificador_interno or None, propietario_id_val, estado, bool(tiene_gas), gas_cuenta or None),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/unidades/nuevo?error=Ya existe una propiedad con ese identificador", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Propiedad creada con éxito", status_code=303)


@router.get("/{unidad_id}/editar")
def form_editar(request: Request, unidad_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM unidades WHERE id = %s;", (unidad_id,))
            unidad = cur.fetchone()
        fields = _campos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar propiedad #{unidad_id}",
        "fields": fields,
        "values": unidad or {},
        "back_url": "/unidades",
    })


@router.post("/{unidad_id}/editar")
def editar(
    unidad_id: int,
    tipo: str = Form(...),
    direccion: str = Form(...),
    identificador_interno: str = Form(""),
    propietario_id: str = Form(""),
    estado: str = Form("vacia"),
    tiene_gas: str = Form(None),
    gas_cuenta: str = Form(""),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    propietario_id_val = int(propietario_id) if propietario_id else None
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE unidades
                SET tipo=%s, direccion=%s, identificador_interno=%s, propietario_id=%s, estado=%s, tiene_gas=%s, gas_cuenta=%s
                WHERE id=%s;
                """,
                (tipo, direccion, identificador_interno or None, propietario_id_val, estado, bool(tiene_gas), gas_cuenta or None, unidad_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/unidades/{unidad_id}/editar?error=Ya existe otra propiedad con ese identificador", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Propiedad actualizada", status_code=303)


@router.post("/{unidad_id}/eliminar")
def eliminar(unidad_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unidades WHERE id = %s;", (unidad_id,))
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return RedirectResponse("/unidades?error=No se puede eliminar: tiene contratos o facturas asociadas", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Propiedad eliminada", status_code=303)
