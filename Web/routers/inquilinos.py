"""
routers/inquilinos.py

Gestión de cuentas de inquilino (rol "inquilino"), solo para admin.

Un inquilino NO se autorregistra: el admin le crea la cuenta eligiendo
un cliente ya cargado en el sistema. La cuenta queda vinculada a ese
cliente vía usuarios.cliente_id, y al iniciar sesión el inquilino ve
únicamente su propia unidad y estado de cuenta (ver main.py / mi_cuenta.html).

Además del alta manual, cuando se crea un contrato se genera sola una
cuenta con usuario "nombre_id" y contraseña "usuario1234" (ver
cuentas_inquilino.py). El botón "Generar cuentas faltantes" de esta
pantalla corre lo mismo para los clientes que ya tenían contrato antes
de que existiera esa generación automática.

Por seguridad las contraseñas se guardan con hash bcrypt y son
irrecuperables: no existe (ni puede existir) una función para "ver" la
contraseña de un inquilino. Lo que el admin puede hacer es restablecerla
(fijar una nueva), que es el equivalente seguro a "verla".
"""

import re

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from cuentas_inquilino import generar_cuentas_faltantes
from database import get_connection
from deps import require_admin, templates, verify_csrf
from security import hash_password

router = APIRouter(prefix="/usuarios/inquilinos", tags=["inquilinos"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _opciones_clientes_disponibles(conn):
    """Clientes que todavía no tienen una cuenta de inquilino asociada."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nombre, apellido, dni_cuit
            FROM clientes
            WHERE id NOT IN (SELECT cliente_id FROM usuarios WHERE cliente_id IS NOT NULL)
            ORDER BY apellido, nombre;
            """
        )
        filas = cur.fetchall()
    if not filas:
        return [{"value": "", "label": "— No hay clientes disponibles (todos ya tienen cuenta) —"}]
    return [
        {"value": f["id"], "label": f"{f['apellido']} {f['nombre']} ({f['dni_cuit']})"}
        for f in filas
    ]


def _campos_nuevo(conn):
    return [
        {"name": "cliente_id", "label": "Cliente", "type": "select", "required": True,
         "options": _opciones_clientes_disponibles(conn)},
        {"name": "nombre_usuario", "label": "Nombre de usuario", "type": "text", "required": True,
         "placeholder": "Ej: jperez"},
        {"name": "email", "label": "Email", "type": "email", "required": True,
         "placeholder": "Ej: juan.perez@email.com"},
        {"name": "password", "label": "Contraseña", "type": "password", "required": True,
         "placeholder": "Mínimo 8 caracteres"},
        {"name": "password2", "label": "Repetir contraseña", "type": "password", "required": True,
         "placeholder": "Repetí la contraseña"},
    ]


def _unidades_de_cliente(conn, cliente_id):
    """Unidad(es) que un cliente tiene o tuvo alquilada(s), vía contratos."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT co.id AS contrato_id, co.estado AS contrato_estado,
                   co.fecha_inicio, co.fecha_fin,
                   un.id AS unidad_id, un.tipo, un.direccion
            FROM contratos co
            JOIN unidades un ON un.id = co.unidad_id
            WHERE co.cliente_id = %s
            ORDER BY (co.estado = 'activo') DESC, co.id DESC;
            """,
            (cliente_id,),
        )
        return cur.fetchall()


def _cantidad_candidatos_faltantes(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT c.id) AS cantidad
            FROM clientes c
            JOIN contratos co ON co.cliente_id = c.id
            WHERE c.id NOT IN (
                SELECT cliente_id FROM usuarios WHERE cliente_id IS NOT NULL
            );
            """
        )
        return cur.fetchone()["cantidad"]


@router.get("")
def listar(request: Request, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.nombre_usuario, u.email, u.activo, u.creado_en,
                       c.id AS cliente_id, c.nombre AS cliente_nombre,
                       c.apellido AS cliente_apellido, c.dni_cuit
                FROM usuarios u
                JOIN clientes c ON c.id = u.cliente_id
                WHERE u.rol = 'inquilino'
                ORDER BY u.id;
                """
            )
            rows = cur.fetchall()
        for row in rows:
            row["unidades"] = _unidades_de_cliente(conn, row["cliente_id"])
        candidatos_faltantes = _cantidad_candidatos_faltantes(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("inquilinos_list.html", {
        "request": request,
        "rows": rows,
        "candidatos_faltantes": candidatos_faltantes,
    })


@router.post("/generar-faltantes")
def generar_faltantes(request: Request, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        resultado = generar_cuentas_faltantes(conn)
    finally:
        conn.close()
    if resultado["creadas"]:
        msg = (
            f"Se generaron {resultado['creadas']} cuenta(s) nueva(s) "
            f"(usuario nombre_id, contraseña usuario1234)."
        )
        if resultado["fallidas"]:
            msg += f" {resultado['fallidas']} no se pudieron generar."
        return RedirectResponse(f"/usuarios/inquilinos?ok={msg}", status_code=303)
    return RedirectResponse(
        "/usuarios/inquilinos?ok=No había cuentas faltantes por generar", status_code=303
    )


@router.get("/nuevo")
def form_nuevo(request: Request, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        fields = _campos_nuevo(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": "Nueva cuenta de inquilino",
        "fields": fields,
        "values": {},
        "back_url": "/usuarios/inquilinos",
    })


@router.post("/nuevo")
def crear(
    request: Request,
    cliente_id: str = Form(""),
    nombre_usuario: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    nombre_usuario = nombre_usuario.strip()
    email = email.strip().lower()

    errores = []
    if not cliente_id:
        errores.append("Elegí un cliente para vincular la cuenta.")
    if len(nombre_usuario) < 3 or len(nombre_usuario) > 50:
        errores.append("El nombre de usuario debe tener entre 3 y 50 caracteres.")
    if not EMAIL_RE.match(email):
        errores.append("El email no es válido.")
    if len(password) < 8:
        errores.append("La contraseña debe tener al menos 8 caracteres.")
    if password != password2:
        errores.append("Las contraseñas no coinciden.")

    conn = get_connection()
    try:
        if errores:
            fields = _campos_nuevo(conn)
            return templates.TemplateResponse("form.html", {
                "request": request,
                "title": "Nueva cuenta de inquilino",
                "fields": fields,
                "values": {
                    "cliente_id": int(cliente_id) if cliente_id else "",
                    "nombre_usuario": nombre_usuario,
                    "email": email,
                },
                "error": " ".join(errores),
                "back_url": "/usuarios/inquilinos",
            }, status_code=400)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (nombre_usuario, email, password_hash, rol, cliente_id)
                    VALUES (%s, %s, %s, 'inquilino', %s);
                    """,
                    (nombre_usuario, email, hash_password(password), int(cliente_id)),
                )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            fields = _campos_nuevo(conn)
            return templates.TemplateResponse("form.html", {
                "request": request,
                "title": "Nueva cuenta de inquilino",
                "fields": fields,
                "values": {"nombre_usuario": nombre_usuario, "email": email},
                "error": "Ya existe una cuenta con ese nombre de usuario o email.",
                "back_url": "/usuarios/inquilinos",
            }, status_code=400)
    finally:
        conn.close()

    return RedirectResponse("/usuarios/inquilinos?ok=Cuenta de inquilino creada con éxito", status_code=303)


@router.post("/{usuario_id}/reset-password")
def reset_password(
    usuario_id: int,
    password: str = Form(...),
    password2: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    if len(password) < 8:
        return RedirectResponse(
            "/usuarios/inquilinos?error=La contraseña debe tener al menos 8 caracteres", status_code=303
        )
    if password != password2:
        return RedirectResponse(
            "/usuarios/inquilinos?error=Las contraseñas no coinciden", status_code=303
        )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios SET password_hash = %s WHERE id = %s AND rol = 'inquilino';",
                (hash_password(password), usuario_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/usuarios/inquilinos?ok=Contraseña restablecida con éxito", status_code=303)


@router.post("/{usuario_id}/estado")
def cambiar_estado(
    usuario_id: int,
    activo: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    nuevo_estado = activo == "true"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios SET activo = %s WHERE id = %s AND rol = 'inquilino';",
                (nuevo_estado, usuario_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/usuarios/inquilinos?ok=Estado actualizado", status_code=303)


@router.post("/{usuario_id}/eliminar")
def eliminar(usuario_id: int, user: dict = Depends(require_admin), _csrf: bool = Depends(verify_csrf)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE id = %s AND rol = 'inquilino';", (usuario_id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/usuarios/inquilinos?ok=Acceso del inquilino eliminado", status_code=303)
