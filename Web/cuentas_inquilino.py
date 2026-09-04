"""
cuentas_inquilino.py

Generación automática de la cuenta de portal de un inquilino.

Pedido: cuando se carga un cliente con un contrato, se le tiene que
generar sola una cuenta para entrar al portal, sin que el admin tenga
que ir a "Usuarios > Inquilinos" a cargarla a mano. Reglas:

- Usuario: nombre_id — el nombre del cliente normalizado (sin acentos,
  minúscula, sin espacios ni símbolos) + "_" + su id de cliente. Por
  ejemplo, cliente #5 llamado "Alan" -> "alan_5". Como el id de
  cliente es único, el nombre de usuario sale único aunque haya dos
  clientes con el mismo nombre de pila.
- Contraseña: siempre "usuario1234", igual para todas las cuentas
  creadas así (el admin puede restablecerla después desde
  /usuarios/inquilinos si hace falta).
- Nunca más de una cuenta por cliente: si el cliente ya tiene una fila
  en usuarios vinculada (cliente_id), no se toca nada.

Se usa desde dos lugares:
- routers/contratos.py, al crear un contrato nuevo (best-effort: si
  algo sale mal acá, el contrato igual queda guardado).
- routers/inquilinos.py, con el botón "Generar cuentas faltantes",
  para los clientes que ya tenían contrato antes de que existiera
  esta función (por ejemplo, los importados del Excel).
"""

from __future__ import annotations

import re
import unicodedata

import psycopg2

from security import hash_password

PASSWORD_INQUILINOS = "usuario1234"
DOMINIO_CUENTAS_AUTOMATICAS = "inquilinos.local"


def _normalizar(texto: str) -> str:
    """"Alan Pablo" -> "alanpablo": saca acentos, espacios y símbolos."""
    texto = texto or ""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto


def _nombre_usuario_base(cliente) -> str:
    base = _normalizar(cliente.get("nombre") or "") or "cliente"
    return f"{base}_{cliente['id']}"


def generar_cuenta_si_falta(conn, cliente_id):
    """
    Crea la cuenta de portal del cliente si todavía no tiene una.
    Hace su propio commit. Devuelve un dict informativo; nunca debería
    hacer falta que quien la llama reaccione al resultado (por eso en
    contratos.py se llama dentro de un try/except que la ignora si
    falla), pero se usa para armar el resumen del botón "Generar
    cuentas faltantes".
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM usuarios WHERE cliente_id = %s LIMIT 1;", (cliente_id,))
        if cur.fetchone():
            return {"creada": False, "motivo": "el cliente ya tiene una cuenta"}

        cur.execute("SELECT id, nombre, apellido FROM clientes WHERE id = %s;", (cliente_id,))
        cliente = cur.fetchone()
    if not cliente:
        return {"creada": False, "motivo": "cliente inexistente"}

    nombre_usuario_base = _nombre_usuario_base(cliente)
    password_hash = hash_password(PASSWORD_INQUILINOS)

    # El nombre de usuario ya debería salir único porque incluye el id
    # del cliente (que es único), pero por las dudas —por ejemplo si
    # ya había una cuenta vieja cargada a mano con ese mismo patrón—
    # probamos con un sufijo antes de rendirnos.
    for intento in range(1, 6):
        sufijo = "" if intento == 1 else str(intento)
        nombre_usuario = f"{nombre_usuario_base}{sufijo}"
        email = f"{nombre_usuario}@{DOMINIO_CUENTAS_AUTOMATICAS}"
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (nombre_usuario, email, password_hash, rol, cliente_id)
                    VALUES (%s, %s, %s, 'inquilino', %s)
                    RETURNING id;
                    """,
                    (nombre_usuario, email, password_hash, cliente_id),
                )
                nuevo_id = cur.fetchone()["id"]
            conn.commit()
            return {
                "creada": True,
                "usuario_id": nuevo_id,
                "nombre_usuario": nombre_usuario,
                "password": PASSWORD_INQUILINOS,
            }
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            continue

    return {"creada": False, "motivo": "no se pudo generar un nombre de usuario único"}


def generar_cuentas_faltantes(conn):
    """
    Recorre todos los clientes que tienen al menos un contrato y
    todavía no tienen cuenta de portal, y se las crea una por una.
    Pensado para correrse una vez y "ponerse al día" con los clientes
    que ya estaban cargados (por ejemplo, los ~190 importados del
    Excel) antes de que existiera la generación automática.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.id
            FROM clientes c
            JOIN contratos co ON co.cliente_id = c.id
            WHERE c.id NOT IN (
                SELECT cliente_id FROM usuarios WHERE cliente_id IS NOT NULL
            )
            ORDER BY c.id;
            """
        )
        ids_candidatos = [f["id"] for f in cur.fetchall()]

    creadas = 0
    fallidas = 0
    for cliente_id in ids_candidatos:
        resultado = generar_cuenta_si_falta(conn, cliente_id)
        if resultado.get("creada"):
            creadas += 1
        else:
            fallidas += 1

    return {"total_candidatos": len(ids_candidatos), "creadas": creadas, "fallidas": fallidas}
