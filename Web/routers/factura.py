"""
routers/facturas_gas.py

Antes esta pantalla era un CRUD clásico (una fila por factura). Ahora
el listado principal (/facturas-gas) es una grilla estilo Excel: una
fila por propiedad con gas, con el inquilino actual, el dueño, el
número de cuenta de gas, una advertencia si debe uno o más meses, y un
selector editable por cada mes del año elegido — para poder cargar
pagos atrasados o adelantados (ej: pagar julio y a la vez completar
febrero, que había quedado pendiente) sin tener que entrar mes por mes.

El alta/edición/borrado de una factura puntual (con monto exacto,
comprobante, vencimiento, etc.) se mantiene disponible en
/facturas-gas/detalle, por si hace falta corregir algo que la grilla
no cubre.

Permisos:
- Ver los listados: cualquier usuario con sesión iniciada.
- Cargar/editar meses o facturas puntuales: solo rol admin (y con
  token CSRF válido).
"""

from __future__ import annotations

from datetime import date

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

router = APIRouter(prefix="/facturas-gas", tags=["facturas_gas"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "unidad_id", "label": "Propiedad (ID)"},
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

MESES = [
    (1, "Ene"), (2, "Feb"), (3, "Mar"), (4, "Abr"), (5, "May"), (6, "Jun"),
    (7, "Jul"), (8, "Ago"), (9, "Sep"), (10, "Oct"), (11, "Nov"), (12, "Dic"),
]

DEUDA_ESTADOS = ("pendiente", "vencido")


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
        {"name": "unidad_id", "label": "Propiedad", "type": "select", "required": True,
         "options": _opciones_unidades(conn)},
        {"name": "periodo", "label": "Período (formato YYYY-MM)", "type": "text", "required": True,
         "placeholder": "Ej: 2026-03", "help": "Formato YYYY-MM, ej: 2026-03"},
        {"name": "monto", "label": "Monto", "type": "number", "step": "0.01", "required": True, "placeholder": "Ej: 15000"},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
        {"name": "vencimiento", "label": "Fecha de vencimiento", "type": "date", "required": False},
        {"name": "pagado_en", "label": "Fecha en que se pagó", "type": "date", "required": False},
    ]


def _anios_disponibles(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT LEFT(periodo, 4) AS anio FROM facturas_gas ORDER BY 1;")
        anios = {int(f["anio"]) for f in cur.fetchall()}
    hoy = date.today().year
    anios.update({hoy - 1, hoy, hoy + 1})
    return sorted(anios)


# ---------------------------------------------------------------------------
# Grilla estilo Excel (pantalla principal)
# ---------------------------------------------------------------------------

@router.get("")
def listar(request: Request, anio: int = 0, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        anio_actual = anio or date.today().year
        anios = _anios_disponibles(conn)
        if anio_actual not in anios:
            anios = sorted(set(anios) | {anio_actual})

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT un.id AS unidad_id, un.direccion, un.tipo, un.gas_cuenta,
                       prop.nombre AS propietario_nombre, prop.apellido AS propietario_apellido,
                       cli.id AS cliente_id, cli.nombre AS cliente_nombre, cli.apellido AS cliente_apellido
                FROM unidades un
                LEFT JOIN propietarios prop ON prop.id = un.propietario_id
                LEFT JOIN LATERAL (
                    SELECT co.cliente_id
                    FROM contratos co
                    WHERE co.unidad_id = un.id
                    ORDER BY (co.estado = 'activo') DESC, co.id DESC
                    LIMIT 1
                ) uc ON true
                LEFT JOIN clientes cli ON cli.id = uc.cliente_id
                WHERE un.tiene_gas = true
                ORDER BY un.id;
                """
            )
            filas = cur.fetchall()

            ids_unidades = [f["unidad_id"] for f in filas]
            por_unidad_mes = {}
            deuda_por_unidad = {}
            if ids_unidades:
                cur.execute(
                    """
                    SELECT unidad_id, periodo, estado
                    FROM facturas_gas
                    WHERE unidad_id = ANY(%s) AND periodo LIKE %s;
                    """,
                    (ids_unidades, f"{anio_actual}-%"),
                )
                for f in cur.fetchall():
                    por_unidad_mes.setdefault(f["unidad_id"], {})[f["periodo"]] = f["estado"]

                cur.execute(
                    """
                    SELECT unidad_id, COUNT(*) AS meses_deuda
                    FROM facturas_gas
                    WHERE unidad_id = ANY(%s) AND estado = ANY(%s)
                    GROUP BY unidad_id;
                    """,
                    (ids_unidades, list(DEUDA_ESTADOS)),
                )
                deuda_por_unidad = {f["unidad_id"]: f["meses_deuda"] for f in cur.fetchall()}
    finally:
        conn.close()

    for f in filas:
        meses_de_la_unidad = por_unidad_mes.get(f["unidad_id"], {})
        f["meses"] = [
            {"num": num, "nombre": nombre, "estado": meses_de_la_unidad.get(f"{anio_actual}-{num:02d}", "")}
            for num, nombre in MESES
        ]
        f["meses_deuda"] = deuda_por_unidad.get(f["unidad_id"], 0)

    return templates.TemplateResponse("facturas_gas_matriz.html", {
        "request": request,
        "filas": filas,
        "anio_actual": anio_actual,
        "anios": anios,
    })


@router.post("/{unidad_id}/guardar-meses")
async def guardar_meses(request: Request, unidad_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    form = await request.form()
    try:
        anio = int(form.get("anio", date.today().year))
    except ValueError:
        anio = date.today().year

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for num, _nombre in MESES:
                valor = (form.get(f"mes_{num:02d}") or "").strip()
                if valor not in ("pagado", "pendiente"):
                    continue  # "—": no se toca ese mes
                periodo = f"{anio}-{num:02d}"
                pagado_en = date.today() if valor == "pagado" else None
                cur.execute(
                    """
                    INSERT INTO facturas_gas (unidad_id, periodo, monto, estado, pagado_en)
                    VALUES (%s, %s, 0, %s, %s)
                    ON CONFLICT (unidad_id, periodo)
                    DO UPDATE SET estado = EXCLUDED.estado, pagado_en = EXCLUDED.pagado_en;
                    """,
                    (unidad_id, periodo, valor, pagado_en),
                )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/facturas-gas?anio={anio}&ok=Meses de gas actualizados", status_code=303)


# ---------------------------------------------------------------------------
# CRUD de detalle (una factura puntual con monto exacto, comprobante, etc.)
# ---------------------------------------------------------------------------

@router.get("/detalle")
def listar_detalle(request: Request, user: dict = Depends(require_staff)):
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
        "back_url": "/facturas-gas/detalle",
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
        return RedirectResponse("/facturas-gas/nuevo?error=Ya existe una factura para esa propiedad en ese período", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas/detalle?ok=Factura creada con éxito", status_code=303)


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
        "back_url": "/facturas-gas/detalle",
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
        return RedirectResponse(f"/facturas-gas/{factura_id}/editar?error=Ya existe otra factura para esa propiedad en ese período", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas/detalle?ok=Factura actualizada", status_code=303)


@router.post("/{factura_id}/eliminar")
def eliminar(factura_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM facturas_gas WHERE id = %s;", (factura_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/facturas-gas/detalle?ok=Factura eliminada", status_code=303)
