"""
routers/contratos.py

CRUD completo de la tabla contratos. Los campos cliente_id y
unidad_id se muestran como selects, cargados dinámicamente desde
las tablas clientes y unidades.

Además del CRUD, cada contrato puede tener configurado un índice de
ajuste (ICL / IPC / RIPTE) y cada cuánto se actualiza. La pantalla
"Actualizar alquiler" (/contratos/{id}/ajustar) trae el valor vigente
del índice, muestra cuál sería el nuevo monto, y solo lo guarda si el
admin lo confirma (nunca se aplica solo) — ver indices_ajuste.py.

Permisos:
- Ver el listado: cualquier usuario con sesión iniciada.
- Crear / editar / eliminar / ajustar: solo rol admin (y con token
  CSRF válido).
"""

from __future__ import annotations

from datetime import date

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, require_staff, templates, verify_csrf
from indices_ajuste import ETIQUETAS_INDICE, calcular_ajuste_contrato, proximo_ajuste

router = APIRouter(prefix="/contratos", tags=["contratos"])

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "cliente_id", "label": "Cliente (ID)"},
    {"key": "unidad_id", "label": "Propiedad (ID)"},
    {"key": "fecha_inicio", "label": "Inicio"},
    {"key": "fecha_fin", "label": "Fin"},
    {"key": "monto_alquiler", "label": "Alquiler"},
    {"key": "dia_vencimiento", "label": "Día venc."},
    {"key": "indice_ajuste_txt", "label": "Ajuste"},
    {"key": "proximo_ajuste_txt", "label": "Próximo ajuste"},
    {"key": "ajustar_link", "label": ""},
    {"key": "estado", "label": "Estado"},
]

ESTADOS = [
    {"value": "activo", "label": "Activo"},
    {"value": "finalizado", "label": "Finalizado"},
    {"value": "rescindido", "label": "Rescindido"},
]

INDICES = [
    {"value": "ninguno", "label": "Sin ajuste por índice"},
    {"value": "icl", "label": "ICL (BCRA)"},
    {"value": "ipc", "label": "IPC (INDEC / inflación)"},
    {"value": "ripte", "label": "RIPTE"},
]

PERIODICIDADES = [
    {"value": "trimestral", "label": "Trimestral"},
    {"value": "semestral", "label": "Semestral"},
    {"value": "anual", "label": "Anual"},
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
        {"name": "unidad_id", "label": "Propiedad", "type": "select", "required": True,
         "options": _opciones_unidades(conn)},
        {"name": "fecha_inicio", "label": "Fecha de inicio", "type": "date", "required": True},
        {"name": "fecha_fin", "label": "Fecha de fin", "type": "date", "required": True},
        {"name": "monto_alquiler", "label": "Monto del alquiler", "type": "number", "step": "0.01", "required": True, "placeholder": "Ej: 150000"},
        {"name": "dia_vencimiento", "label": "Día de vencimiento (1-31)", "type": "number", "required": True, "placeholder": "Ej: 10"},
        {"name": "deposito", "label": "Depósito", "type": "number", "step": "0.01", "required": False, "placeholder": "Ej: 150000 (0 si no aplica)"},
        {"name": "indice_ajuste", "label": "Índice de ajuste", "type": "select", "required": True, "options": INDICES,
         "help": "IPC, ICL o RIPTE — hay una explicación detallada de cada uno en la lista de Contratos."},
        {"name": "periodicidad_ajuste", "label": "Cada cuánto se ajusta", "type": "select", "required": True, "options": PERIODICIDADES},
        {"name": "estado", "label": "Estado", "type": "select", "required": True, "options": ESTADOS},
    ]


def _obtener_contrato(conn, contrato_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM contratos WHERE id = %s;", (contrato_id,))
        return cur.fetchone()


@router.get("")
def listar(request: Request, user: dict = Depends(require_staff)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM contratos ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()

    hoy = date.today()
    for fila in rows:
        fila["indice_ajuste_txt"] = ETIQUETAS_INDICE.get(fila["indice_ajuste"], fila["indice_ajuste"])
        if fila["indice_ajuste"] != "ninguno":
            fecha_prox = proximo_ajuste(fila)
            vencido = fecha_prox <= hoy
            fila["proximo_ajuste_txt"] = fecha_prox.strftime("%d/%m/%Y") + (" (vencido)" if vencido else "")
            fila["ajustar_link"] = True
        else:
            fila["proximo_ajuste_txt"] = "—"
            fila["ajustar_link"] = False

    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Contratos",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/contratos",
        "add_url": "/contratos/nuevo",
    })


@router.get("/indices-ayuda")
def indices_ayuda(request: Request, user: dict = Depends(require_staff)):
    return templates.TemplateResponse("contratos_indices_ayuda.html", {"request": request})


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
        "values": {"indice_ajuste": "ninguno", "periodicidad_ajuste": "anual"},
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
    indice_ajuste: str = Form("ninguno"),
    periodicidad_ajuste: str = Form("anual"),
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
                     monto_alquiler, dia_vencimiento, deposito, estado,
                     indice_ajuste, periodicidad_ajuste, monto_base, fecha_ultimo_ajuste)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (cliente_id, unidad_id, fecha_inicio, fecha_fin,
                 monto_alquiler, dia_vencimiento, deposito, estado,
                 indice_ajuste, periodicidad_ajuste, monto_alquiler, fecha_inicio),
            )
            nuevo_id = cur.fetchone()["id"]
            # Igual que en los scripts de consola: al crear el contrato,
            # la unidad pasa a estar ocupada.
            cur.execute("UPDATE unidades SET estado = 'ocupada' WHERE id = %s;", (unidad_id,))
        conn.commit()

        try:
            from cuentas_inquilino import generar_cuenta_si_falta
            generar_cuenta_si_falta(conn, cliente_id)
        except Exception:
            pass
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
        contrato = _obtener_contrato(conn, contrato_id)
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
    indice_ajuste: str = Form("ninguno"),
    periodicidad_ajuste: str = Form("anual"),
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
                    monto_alquiler=%s, dia_vencimiento=%s, deposito=%s, estado=%s,
                    indice_ajuste=%s, periodicidad_ajuste=%s
                WHERE id=%s;
                """,
                (cliente_id, unidad_id, fecha_inicio, fecha_fin,
                 monto_alquiler, dia_vencimiento, deposito, estado,
                 indice_ajuste, periodicidad_ajuste, contrato_id),
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


# ---------------------------------------------------------------------------
# Ajuste de alquiler por índice
# ---------------------------------------------------------------------------

@router.get("/{contrato_id}/ajustar")
def form_ajustar(request: Request, contrato_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        contrato = _obtener_contrato(conn, contrato_id)
    finally:
        conn.close()
    if not contrato:
        return RedirectResponse("/contratos?error=Ese contrato no existe", status_code=303)

    contexto = {
        "request": request,
        "contrato": contrato,
        "indice_txt": ETIQUETAS_INDICE.get(contrato["indice_ajuste"], contrato["indice_ajuste"]),
    }
    if contrato["indice_ajuste"] != "ninguno":
        contexto["proximo"] = proximo_ajuste(contrato)
        contexto["vencido"] = contexto["proximo"] <= date.today()
    return templates.TemplateResponse("contrato_ajustar.html", contexto)


@router.post("/{contrato_id}/ajustar/calcular")
def calcular(request: Request, contrato_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        contrato = _obtener_contrato(conn, contrato_id)
        if not contrato:
            return RedirectResponse("/contratos?error=Ese contrato no existe", status_code=303)
        resultado = calcular_ajuste_contrato(conn, contrato)
        conn.commit()  # guarda en caché los valores de índice que se hayan traído, aunque el cálculo falle a mitad de camino
    finally:
        conn.close()

    contexto = {
        "request": request,
        "contrato": contrato,
        "indice_txt": ETIQUETAS_INDICE.get(contrato["indice_ajuste"], contrato["indice_ajuste"]),
        "resultado": resultado,
    }
    return templates.TemplateResponse("contrato_ajustar.html", contexto)


@router.post("/{contrato_id}/ajustar/confirmar")
def confirmar_ajuste(
    contrato_id: int,
    nuevo_monto: float = Form(...),
    valor_indice_nuevo: str = Form(""),
    fecha_valor_nuevo: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    conn = get_connection()
    try:
        contrato = _obtener_contrato(conn, contrato_id)
        if not contrato:
            return RedirectResponse("/contratos?error=Ese contrato no existe", status_code=303)
        with conn.cursor() as cur:
            if contrato["indice_ajuste"] == "icl" and valor_indice_nuevo:
                cur.execute(
                    """
                    UPDATE contratos
                    SET monto_alquiler=%s, monto_base=%s, valor_indice_base=%s, fecha_ultimo_ajuste=%s
                    WHERE id=%s;
                    """,
                    (nuevo_monto, nuevo_monto, valor_indice_nuevo, fecha_valor_nuevo, contrato_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE contratos
                    SET monto_alquiler=%s, monto_base=%s, fecha_ultimo_ajuste=%s
                    WHERE id=%s;
                    """,
                    (nuevo_monto, nuevo_monto, fecha_valor_nuevo, contrato_id),
                )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return RedirectResponse(f"/contratos/{contrato_id}/ajustar?error=No se pudo guardar el ajuste: {e}", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(f"/contratos?ok=Alquiler actualizado a ${nuevo_monto:.2f}", status_code=303)
