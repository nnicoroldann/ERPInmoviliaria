"""
mercadopago_client.py

Wrapper mínimo sobre la API REST de Mercado Pago (Checkout Pro), sin
depender del SDK oficial. Solo dos operaciones:

- crear_preferencia(...): genera un "checkout" al que redirigimos al
  inquilino para que pague. Devuelve la URL a la que hay que mandarlo.
- obtener_pago(payment_id): consulta el estado real de un pago en la
  API de Mercado Pago. El webhook SIEMPRE debe usar esto para confirmar
  un cobro, nunca confiar en lo que venga en la notificación en sí,
  porque cualquiera podría mandarnos un POST fingiendo un pago aprobado.

Documentación oficial (por si algo cambia con el tiempo):
  https://www.mercadopago.com.ar/developers/es/reference

Requiere en Web/.env:
    MP_ACCESS_TOKEN=TEST-xxxxxxxx...   (o el access token de producción)
"""

import os

import requests

API_BASE = "https://api.mercadopago.com"


class MercadoPagoError(Exception):
    """Se lanza si falta configuración o la API de Mercado Pago responde
    con un error. El router la atrapa y le muestra un mensaje claro al
    usuario en vez de romper la página."""


def _access_token() -> str:
    token = os.getenv("MP_ACCESS_TOKEN", "").strip()
    if not token:
        raise MercadoPagoError(
            "Los pagos online todavía no están configurados: falta MP_ACCESS_TOKEN en Web/.env."
        )
    return token


def crear_preferencia(items: list[dict], external_reference: str, back_urls: dict, notification_url: str) -> dict:
    """Crea una preferencia de pago (Checkout Pro) y devuelve la
    respuesta completa de Mercado Pago (incluye "id", "init_point" y
    "sandbox_init_point").

    items: lista de {"title": str, "quantity": int, "unit_price": float}
    external_reference: string propia para identificar el pago después
        (acá usamos el preference_id que ya generamos nosotros, ver pagos.py)
    back_urls: {"success": url, "failure": url, "pending": url}
    notification_url: URL pública de nuestro webhook (/pagos/webhook)
    """
    payload = {
        "items": [
            {
                "title": item["title"],
                "quantity": item["quantity"],
                "unit_price": round(float(item["unit_price"]), 2),
                "currency_id": "ARS",
            }
            for item in items
        ],
        "external_reference": external_reference,
        "back_urls": back_urls,
        "auto_return": "approved",
        "notification_url": notification_url,
    }
    try:
        resp = requests.post(
            f"{API_BASE}/checkout/preferences",
            headers={"Authorization": f"Bearer {_access_token()}"},
            json=payload,
            timeout=15,
        )
    except requests.RequestException as e:
        raise MercadoPagoError(f"No se pudo conectar con Mercado Pago: {e}") from e

    if resp.status_code not in (200, 201):
        raise MercadoPagoError(
            f"Mercado Pago rechazó la preferencia de pago (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


def obtener_pago(payment_id: str) -> dict:
    """Consulta el estado real de un pago directamente en la API de
    Mercado Pago. Devuelve el JSON completo (interesan sobre todo
    "status" y "external_reference")."""
    try:
        resp = requests.get(
            f"{API_BASE}/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=15,
        )
    except requests.RequestException as e:
        raise MercadoPagoError(f"No se pudo conectar con Mercado Pago: {e}") from e

    if resp.status_code != 200:
        raise MercadoPagoError(
            f"Mercado Pago no pudo confirmar el pago {payment_id} (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()
