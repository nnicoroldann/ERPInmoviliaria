"""
routers/cuotas.py

Antes esta pantalla era un CRUD clásico (una fila por cuota). Ahora el
listado principal (/cuotas) es una grilla estilo Excel: una fila por
contrato, con el inquilino, la propiedad y el alquiler, una
advertencia si debe una o más cuotas, y un selector editable por cada
mes del año elegido — para poder cargar pagos atrasados o adelantados
sin tener que entrar mes por mes (ej: pagar noviembre y diciembre,
volver a enero del año siguiente, y que diciembre quede disponible en
el historial).

Cada fila tiene un link "Historial" con TODAS las cuotas de ese
contrato, de cualquier año, para poder verlas incluso después de que
"pasen de año" en la grilla principal.

El alta/edición/borrado de una cuota puntual (con comprobante, un
monto distinto al del contrato, etc.) se mantiene disponible en
/cuotas/detalle.

Permisos:
- Ver los listados: cualquier usuario con sesión iniciada.
- Cargar/editar cuotas: solo rol admin (y con token CSRF válido).
"""

from __future__ import annotations

from datetime import date

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf

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

MESES = [
    (1, "Ene"), (2, "Feb"), (3, "Mar"), (4, "Abr"), (5, "May"), (6, "Jun"),
    (7, "Jul"), (8, "Ago"), (9, "Sep"), (10, "Oct"), (11, "Nov"), (12, "Dic"),
]

DEUDA_ESTADOS = ("pendiente", "vencido", "parcial")
VALORES_MES_VALIDOS = ("pagado", "pendiente", "parcial")


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
         "placeholder": "Ej: 2026-03", "help": "Formato YYYY-MM, ej: 2026-03"},
        {"name": "monto", "label": "Monto", "type": "number", "step": "0.01", "required": True, "placeholder": "Ej: 150000"},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
        {"name": "fecha_pago", "label": "Fecha de pago", "type": "date", "required": False},
        {"name": "comprobante", "label": "Comprobante", "type": "text", "required": False, "placeholder": "Ej: Transferencia #4521"},
    ]


def _anios_disponibles(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT LEFT(mes, 4) AS anio FROM cuotas ORDER BY 1;")
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
                SELECT co.id AS contrato_id, co.estado AS contrato_estado, co.monto_alquiler,
                       cl.id AS cliente_id, cl.nombre AS cliente_nombre, cl.apellido AS cliente_apellido,
                       un.tipo, un.direccion
                FROM contratos co
                JOIN clientes cl ON cl.id = co.cliente_id
                JOIN unidades un ON un.id = co.unidad_id
                ORDER BY (co.estado = 'activo') DESC, co.id DESC;
                """
            )
            filas = cur.fetchall()

            ids_contratos = [f["contrato_id"] for f in filas]
            por_contrato_mes = {}
            deuda_por_contrato = {}
            if ids_contratos:
                cur.execute(
                    """
                    SELECT contrato_id, mes, estado
                    FROM cuotas
                    WHERE contrato_id = ANY(%s) AND mes LIKE %s;
                    """,
                    (ids_contratos, f"{anio_actual}-%"),
                )
                for f in cur.fetchall():
                    por_contrato_mes.setdefault(f["contrato_id"], {})[f["mes"]] = f["estado"]

                cur.execute(
                    """
                    SELECT contrato_id, COUNT(*) AS cuotas_deuda
                    FROM cuotas
                    WHERE contrato_id = ANY(%s) AND estado = ANY(%s)
                    GROUP BY contrato_id;
                    """,
                    (ids_contratos, list(DEUDA_ESTADOS)),
                )
                deuda_por_contrato = {f["contrato_id"]: f["cuotas_deuda"] for f in cur.fetchall()}
    finally:
        conn.close()

    for f in filas:
        meses_del_contrato = por_contrato_mes.get(f["contrato_id"], {})
        f["meses"] = [
            {"num": num, "nombre": nombre, "estado": meses_del_contrato.get(f"{anio_actual}-{num:02d}", "")}
            for num, nombre in MESES
        ]
        f["cuotas_deuda"] = deuda_por_contrato.get(f["contrato_id"], 0)

    return templates.TemplateResponse("cuotas_matriz.html", {
        "request": request,
        "filas": filas,
        "anio_actual": anio_actual,
        "anios": anios,
    })


@router.post("/{contrato_id}/guardar-meses")
async def guardar_meses(request: Request, contrato_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    form = await request.form()
    try:
        anio = int(form.get("anio", date.today().year))
    except ValueError:
        anio = date.today().year

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT monto_alquiler FROM contratos WHERE id = %s;", (contrato_id,))
            contrato = cur.fetchone()
            if not contrato:
                return RedirectResponse("/cuotas?error=Ese contrato no existe", status_code=303)
            monto_defecto = contrato["monto_alquiler"]

            for num, _nombre in MESES:
                valor = (form.get(f"mes_{num:02d}") or "").strip()
                if valor not in VALORES_MES_VALIDOS:
                    continue  # "—": no se toca ese mes
                mes = f"{anio}-{num:02d}"
                fecha_pago = date.today() if valor == "pagado" else None
                cur.execute(
                    """
                    INSERT INTO cuotas (contrato_id, mes, monto, estado, fecha_pago)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (contrato_id, mes)
                    DO UPDATE SET estado = EXCLUDED.estado, fecha_pago = EXCLUDED.fecha_pago;
                    """,
                    (contrato_id, mes, monto_defecto, valor, fecha_pago),
                )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/cuotas?anio={anio}&ok=Cuotas actualizadas", status_code=303)


@router.get("/{contrato_id}/historial")
def historial(request: Request, contrato_id: int, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT co.id, co.monto_alquiler, co.estado AS contrato_estado,
                       cl.nombre AS cliente_nombre, cl.apellido AS cliente_apellido,
                       un.tipo, un.direccion
                FROM contratos co
                JOIN clientes cl ON cl.id = co.cliente_id
                JOIN unidades un ON un.id = co.unidad_id
                WHERE co.id = %s;
                """,
                (contrato_id,),
            )
            contrato = cur.fetchone()
            if not contrato:
                return RedirectResponse("/cuotas?error=Ese contrato no existe", status_code=303)

            cur.execute("SELECT * FROM cuotas WHERE contrato_id = %s ORDER BY mes DESC;", (contrato_id,))
            cuotas = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("cuotas_historial.html", {
        "request": request,
        "contrato": contrato,
        "cuotas": cuotas,
    })


# ---------------------------------------------------------------------------
# CRUD de detalle (una cuota puntual con comprobante, monto distinto, etc.)
# ---------------------------------------------------------------------------

@router.get("/detalle")
def listar_detalle(request: Request, user: dict = Depends(require_staff)):
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
        "back_url": "/cuotas/detalle",
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
    return RedirectResponse("/cuotas/detalle?ok=Cuota creada con éxito", status_code=303)


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
        "back_url": "/cuotas/detalle",
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
    return RedirectResponse("/cuotas/detalle?ok=Cuota actualizada", status_code=303)


@router.post("/{cuota_id}/eliminar")
def eliminar(cuota_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cuotas WHERE id = %s;", (cuota_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/cuotas/detalle?ok=Cuota eliminada", status_code=303)
