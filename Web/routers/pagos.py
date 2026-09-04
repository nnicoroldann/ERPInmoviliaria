"""
routers/pagos.py

Pagos online de cuotas y facturas con Mercado Pago (Checkout Pro).

Flujo:
1. El inquilino aprieta "Pagar" en su portal -> creamos una preferencia
   de pago en Mercado Pago y lo mandamos a esa URL de checkout.
2. Paga (o no) en el sitio de Mercado Pago.
3. Mercado Pago:
     a) le manda una notificación a /pagos/webhook confirmando el pago
        (esto es lo que realmente marca la cuota/factura como pagada)
     b) lo redirige de vuelta a /pagos/resultado, solo para mostrarle
        un mensaje - esa redirección NO confirma el pago, porque el
        usuario podría cerrar el navegador antes de volver.

Seguridad: el webhook nunca confía en lo que le llega en el POST/GET;
siempre vuelve a consultar el pago directamente en la API de Mercado
Pago con nuestro access token antes de marcar algo como pagado.

Para que el webhook funcione, Web/.env necesita APP_BASE_URL con una
URL pública de verdad (Mercado Pago tiene que poder llegar a ella desde
internet; "localhost" no sirve). Para probar en desarrollo se puede usar
una herramienta como ngrok.
"""

import os
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import get_current_user, require_admin, require_staff, templates, verify_csrf
from mercadopago_client import MercadoPagoError, crear_preferencia, obtener_pago

router = APIRouter(prefix="/pagos", tags=["pagos"])

ESTADOS_PAGABLES_CUOTA = ("pendiente", "vencido", "parcial")
ESTADOS_PAGABLES_FACTURA = ("pendiente", "vencido")


def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def _error(mensaje) -> RedirectResponse:
    return RedirectResponse(f"/?error={quote(str(mensaje))}", status_code=303)


def _contrato_del_inquilino(conn, user: dict, contrato_id: int):
    """Devuelve el contrato si pertenece al cliente logueado, o None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM contratos WHERE id = %s AND cliente_id = %s;",
            (contrato_id, user.get("cliente_id")),
        )
        return cur.fetchone()


def _contrato_de_la_unidad_del_inquilino(conn, user: dict, unidad_id: int):
    """Devuelve el contrato (de ese inquilino) que corresponde a esa
    unidad, si existe, para poder validar que una factura de gas/agua
    es realmente suya."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM contratos
            WHERE cliente_id = %s AND unidad_id = %s
            ORDER BY (estado = 'activo') DESC, id DESC
            LIMIT 1;
            """,
            (user.get("cliente_id"), unidad_id),
        )
        return cur.fetchone()


def _crear_pago(conn, items_db) -> str:
    """items_db: lista de dicts {tipo, referencia_id, contrato_id, titulo, monto}.
    Crea la preferencia en Mercado Pago, guarda una fila en
    pagos_mercadopago por cada ítem (todas con el mismo grupo_pago) y
    devuelve la URL de checkout a la que hay que redirigir."""
    grupo = secrets.token_urlsafe(24)

    with conn.cursor() as cur:
        for item in items_db:
            cur.execute(
                """
                INSERT INTO pagos_mercadopago (tipo, referencia_id, contrato_id, grupo_pago, monto, estado)
                VALUES (%s, %s, %s, %s, %s, 'pendiente');
                """,
                (item["tipo"], item["referencia_id"], item["contrato_id"], grupo, item["monto"]),
            )
    conn.commit()

    preferencia = crear_preferencia(
        items=[{"title": item["titulo"], "quantity": 1, "unit_price": item["monto"]} for item in items_db],
        external_reference=grupo,
        back_urls={
            "success": f"{_base_url()}/pagos/resultado?status=approved",
            "failure": f"{_base_url()}/pagos/resultado?status=rejected",
            "pending": f"{_base_url()}/pagos/resultado?status=pending",
        },
        notification_url=f"{_base_url()}/pagos/webhook",
    )

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pagos_mercadopago SET mp_preference_id = %s WHERE grupo_pago = %s;",
            (preferencia.get("id"), grupo),
        )
    conn.commit()

    # sandbox_init_point aparece cuando el access token es de prueba (TEST-...)
    return preferencia.get("sandbox_init_point") or preferencia.get("init_point")


@router.get("")
def listar(request: Request, user: dict = Depends(require_staff)):
    """Panel de solo lectura para el admin: qué se cobró por Mercado
    Pago, a quién y en qué estado quedó. Sirve para revisar si algún
    webhook falló, ahora que hay dinero real circulando."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.*, cl.nombre AS cliente_nombre, cl.apellido AS cliente_apellido
                FROM pagos_mercadopago p
                JOIN contratos co ON co.id = p.contrato_id
                JOIN clientes cl ON cl.id = co.cliente_id
                ORDER BY p.creado_en DESC;
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("pagos_list.html", {
        "request": request,
        "rows": rows,
    })


@router.post("/cuota/{cuota_id}")
def pagar_cuota(
    cuota_id: int,
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    if user.get("rol") != "inquilino":
        return _error("Esta acción es solo para inquilinos")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cuotas WHERE id = %s;", (cuota_id,))
            cuota = cur.fetchone()
        if not cuota:
            return _error("No se encontró esa cuota")

        contrato = _contrato_del_inquilino(conn, user, cuota["contrato_id"])
        if not contrato:
            return _error("Esa cuota no pertenece a tu cuenta")

        if cuota["estado"] not in ESTADOS_PAGABLES_CUOTA:
            return _error("Esa cuota ya está pagada")

        try:
            url = _crear_pago(conn, [{
                "tipo": "cuota", "referencia_id": cuota["id"], "contrato_id": contrato["id"],
                "titulo": f"Alquiler {cuota['mes']}", "monto": cuota["monto"],
            }])
        except MercadoPagoError as e:
            return _error(e)
    finally:
        conn.close()
    return RedirectResponse(url, status_code=303)


def _pagar_factura(factura_id: int, user: dict, tabla: str, tipo: str, etiqueta: str, _csrf: bool):
    if user.get("rol") != "inquilino":
        return _error("Esta acción es solo para inquilinos")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {tabla} WHERE id = %s;", (factura_id,))
            factura = cur.fetchone()
        if not factura:
            return _error("No se encontró esa factura")

        contrato = _contrato_de_la_unidad_del_inquilino(conn, user, factura["unidad_id"])
        if not contrato:
            return _error("Esa factura no pertenece a tu cuenta")

        if factura["estado"] not in ESTADOS_PAGABLES_FACTURA:
            return _error("Esa factura ya está pagada")

        try:
            url = _crear_pago(conn, [{
                "tipo": tipo, "referencia_id": factura["id"], "contrato_id": contrato["id"],
                "titulo": f"{etiqueta} {factura['periodo']}", "monto": factura["monto"],
            }])
        except MercadoPagoError as e:
            return _error(e)
    finally:
        conn.close()
    return RedirectResponse(url, status_code=303)


@router.post("/factura-gas/{factura_id}")
def pagar_factura_gas(
    factura_id: int,
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    return _pagar_factura(factura_id, user, "facturas_gas", "gas", "Gas", _csrf)


@router.post("/factura-agua/{factura_id}")
def pagar_factura_agua(
    factura_id: int,
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    return _pagar_factura(factura_id, user, "facturas_agua", "agua", "Agua", _csrf)


@router.post("/contrato/{contrato_id}/todo")
def pagar_todo(
    contrato_id: int,
    user: dict = Depends(get_current_user),
    _csrf: bool = Depends(verify_csrf),
):
    if user.get("rol") != "inquilino":
        return _error("Esta acción es solo para inquilinos")

    conn = get_connection()
    try:
        contrato = _contrato_del_inquilino(conn, user, contrato_id)
        if not contrato:
            return _error("Ese contrato no pertenece a tu cuenta")

        items = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM cuotas WHERE contrato_id = %s AND estado = ANY(%s);",
                (contrato_id, list(ESTADOS_PAGABLES_CUOTA)),
            )
            for cuota in cur.fetchall():
                items.append({"tipo": "cuota", "referencia_id": cuota["id"], "contrato_id": contrato_id,
                              "titulo": f"Alquiler {cuota['mes']}", "monto": cuota["monto"]})

            cur.execute(
                "SELECT * FROM facturas_gas WHERE unidad_id = %s AND estado = ANY(%s);",
                (contrato["unidad_id"], list(ESTADOS_PAGABLES_FACTURA)),
            )
            for f in cur.fetchall():
                items.append({"tipo": "gas", "referencia_id": f["id"], "contrato_id": contrato_id,
                              "titulo": f"Gas {f['periodo']}", "monto": f["monto"]})

        if not items:
            return RedirectResponse("/?ok=No tenés nada pendiente para pagar", status_code=303)

        try:
            url = _crear_pago(conn, items)
        except MercadoPagoError as e:
            return _error(e)
    finally:
        conn.close()
    return RedirectResponse(url, status_code=303)


@router.get("/resultado")
def resultado(status: str = "pending"):
    """Adonde Mercado Pago devuelve al navegador después del checkout.
    Es solo un mensaje para el usuario: lo que realmente confirma el
    pago es el webhook (más abajo), no esta redirección."""
    if status == "approved":
        return RedirectResponse(
            "/?ok=¡Pago recibido! Puede tardar unos segundos en reflejarse acá.", status_code=303
        )
    if status == "pending":
        return RedirectResponse("/?ok=Tu pago quedó pendiente de confirmación.", status_code=303)
    return RedirectResponse("/?error=El pago no se completó. Podés intentarlo de nuevo.", status_code=303)


@router.post("/webhook")
@router.get("/webhook")
async def webhook(request: Request):
    """Mercado Pago llama acá para avisar de un pago. No requiere
    sesión ni CSRF (lo llama el servidor de Mercado Pago, no un
    navegador con nuestra cookie): la validación real es volver a
    consultar el pago con nuestro access token, nunca confiar en el
    contenido de esta llamada."""
    payment_id = request.query_params.get("id") or request.query_params.get("data.id")
    topic = request.query_params.get("topic") or request.query_params.get("type")

    if not payment_id:
        try:
            body = await request.json()
        except Exception:
            body = {}
        payment_id = (body.get("data") or {}).get("id")
        topic = topic or body.get("type")

    if not payment_id or topic not in (None, "payment"):
        # Mercado Pago también manda notificaciones de "merchant_order"
        # u otros tipos que no nos interesan acá.
        return {"status": "ignorado"}

    try:
        pago = obtener_pago(payment_id)
    except MercadoPagoError:
        # Si todavía no se puede confirmar, no hacemos nada: Mercado
        # Pago reintenta la notificación más tarde.
        return {"status": "no se pudo confirmar, se ignora por ahora"}

    grupo = pago.get("external_reference")
    estado_mp = pago.get("status")  # approved | pending | rejected | ...
    if not grupo:
        return {"status": "sin referencia"}

    nuevo_estado = "aprobado" if estado_mp == "approved" else ("rechazado" if estado_mp == "rejected" else "pendiente")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pagos_mercadopago WHERE grupo_pago = %s;", (grupo,))
            filas = cur.fetchall()

            for fila in filas:
                cur.execute(
                    """
                    UPDATE pagos_mercadopago
                    SET estado = %s, mp_payment_id = %s, actualizado_en = now()
                    WHERE id = %s;
                    """,
                    (nuevo_estado, str(payment_id), fila["id"]),
                )
                if nuevo_estado == "aprobado":
                    if fila["tipo"] == "cuota":
                        cur.execute(
                            "UPDATE cuotas SET estado = 'pagado', fecha_pago = CURRENT_DATE WHERE id = %s;",
                            (fila["referencia_id"],),
                        )
                    elif fila["tipo"] == "gas":
                        cur.execute(
                            "UPDATE facturas_gas SET estado = 'pagado', pagado_en = CURRENT_DATE WHERE id = %s;",
                            (fila["referencia_id"],),
                        )
                    elif fila["tipo"] == "agua":
                        cur.execute(
                            "UPDATE facturas_agua SET estado = 'pagado', pagado_en = CURRENT_DATE WHERE id = %s;",
                            (fila["referencia_id"],),
                        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}
