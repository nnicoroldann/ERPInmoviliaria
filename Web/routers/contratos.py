"""
routers/contratos.py

CRUD completo de la tabla contratos. Los campos cliente_id y
unidad_id se muestran como selects, cargados dinámicamente desde
las tablas clientes y unidades.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar: solo rol admin (y con token CSRF válido).
"""

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/contratos", tags=["contratos"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "cliente_id", "label": "Cliente (ID)"},
    {"key": "unidad_id", "label": "Unidad (ID)"},
    {"key": "fecha_inicio", "label": "Inicio"},
    {"key": "fecha_fin", "label": "Fin"},
    {"key": "monto_alquiler", "label": "Alquiler"},
    {"key": "dia_vencimiento", "label": "Día venc."},
    {"key": "estado", "label": "Estado"},
]

ESTADOS = [
    {"value": "activo", "label": "Activo"},
    {"value": "finalizado", "label": "Finalizado"},
    {"value": "rescindido", "label": "Rescindido"},
]


def _opciones_clientes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, nombre, apellido, dni_cuit FROM clientes ORDER BY id;")
        filas = cur.fetchall()
    return [
        {"value": f["id"], "label": f"{f['id']} - {f['nombre']} {f['apellido']} ({f['dni_cuit']})"}
        for f in filas
    ]


def _opciones_unidades(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, tipo, direccion FROM unidades ORDER BY id;")
        filas = cur.fetchall()
    return [
        {"value": f["id"], "label": f"{f['id']} - {f['tipo']} en {f['direccion']}"}
        for f in filas
    ]


def _campos(conn):
    return [
        {"name": "cliente_id", "label": "Cliente", "type": "select", "required": True,
         "options": _opciones_clientes(conn)},
        {"name": "unidad_id", "label": "Unidad", "type": "select", "required": True,
         "options": _opciones_unidades(conn)},
        {"name": "fecha_inicio", "label": "Fecha de inicio", "type": "date", "required": True},
        {"name": "fecha_fin", "label": "Fecha de fin", "type": "date", "required": True},
        {"name": "monto_alquiler", "label": "Monto del alquiler", "type": "number", "step": "0.01", "required": True, "placeholder": "Ej: 150000"},
        {"name": "dia_vencimiento", "label": "Día de vencimiento (1-31)", "type": "number", "required": True, "placeholder": "Ej: 10"},
        {"name": "deposito", "label": "Depósito", "type": "number", "step": "0.01", "required": False, "placeholder": "Ej: 150000 (0 si no aplica)"},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
    ]


@router.get("")
def listar(request: Request, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contratos ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Contratos",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/contratos",
        "add_url": "/contratos/nuevo",
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
        "title": "Nuevo contrato",
        "fields": fields,
        "values": {},
        "back_url": "/contratos",
    })


@router.post("/nuevo")
def crear(
    cliente_id: int = Form(...),
    unidad_id: int = Form(...),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    monto_alquiler: float = Form(...),
    dia_vencimiento: int = Form(...),
    deposito: float = Form(0),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contratos
                    (cliente_id, unidad_id, fecha_inicio, fecha_fin,
                     monto_alquiler, dia_vencimiento, deposito, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (cliente_id, unidad_id, fecha_inicio, fecha_fin,
                 monto_alquiler, dia_vencimiento, deposito, estado),
            )
            # Igual que en los scripts de consola: al crear el contrato,
            # la unidad pasa a estar ocupada.
            cur.execute("UPDATE unidades SET estado = 'ocupada' WHERE id = %s;", (unidad_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return RedirectResponse(f"/contratos/nuevo?error=Error al crear el contrato: {e}", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/contratos?ok=Contrato creado con éxito", status_code=303)


@router.get("/{contrato_id}/editar")
def form_editar(request: Request, contrato_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contratos WHERE id = %s;", (contrato_id,))
            contrato = cur.fetchone()
        fields = _campos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar contrato #{contrato_id}",
        "fields": fields,
        "values": contrato or {},
        "back_url": "/contratos",
    })


@router.post("/{contrato_id}/editar")
def editar(
    contrato_id: int,
    cliente_id: int = Form(...),
    unidad_id: int = Form(...),
    fecha_inicio: str = Form(...),
    fecha_fin: str = Form(...),
    monto_alquiler: float = Form(...),
    dia_vencimiento: int = Form(...),
    deposito: float = Form(0),
    estado: str = Form("activo"),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE contratos
                SET cliente_id=%s, unidad_id=%s, fecha_inicio=%s, fecha_fin=%s,
                    monto_alquiler=%s, dia_vencimiento=%s, deposito=%s, estado=%s
                WHERE id=%s;
                """,
                (cliente_id, unidad_id, fecha_inicio, fecha_fin,
                 monto_alquiler, dia_vencimiento, deposito, estado, contrato_id),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return RedirectResponse(f"/contratos/{contrato_id}/editar?error=Error al actualizar: {e}", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/contratos?ok=Contrato actualizado", status_code=303)


@router.post("/{contrato_id}/eliminar")
def eliminar(contrato_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM contratos WHERE id = %s;", (contrato_id,))
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return RedirectResponse("/contratos?error=No se puede eliminar: tiene cuotas asociadas", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/contratos?ok=Contrato eliminado", status_code=303)
