"""
routers/usuarios.py

Panel de administración de cuentas (solo accesible para rol admin):
listar usuarios, cambiar su rol y activar/desactivar cuentas.

Un admin no puede quitarse a sí mismo el rol de admin ni
desactivar su propia cuenta (para evitar quedarse afuera del sistema).
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import require_admin, templates, verify_csrf

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.get("")
def listar(request: Request, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Las cuentas de inquilino se gestionan aparte, en
            # /usuarios/inquilinos: acá solo se listan admin/usuario
            # (personal de la inmobiliaria).
            cur.execute(
                "SELECT id, nombre_usuario, email, rol, activo, creado_en "
                "FROM usuarios WHERE rol IN ('admin', 'usuario') ORDER BY id;"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("usuarios.html", {
        "request": request,
        "rows": rows,
    })


@router.post("/{usuario_id}/rol")
def cambiar_rol(
    request: Request,
    usuario_id: int,
    rol: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    if rol not in ("admin", "usuario"):
        return RedirectResponse("/usuarios?error=Rol inválido", status_code=303)
    if usuario_id == user["id"] and rol != "admin":
        return RedirectResponse(
            "/usuarios?error=No podés quitarte el rol de administrador a vos mismo",
            status_code=303,
        )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # El AND protege una cuenta de inquilino de que este endpoint
            # (pensado solo para personal admin/usuario) le cambie el rol.
            cur.execute(
                "UPDATE usuarios SET rol = %s WHERE id = %s AND rol IN ('admin', 'usuario');",
                (rol, usuario_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/usuarios?ok=Rol actualizado", status_code=303)


@router.post("/{usuario_id}/estado")
def cambiar_estado(
    request: Request,
    usuario_id: int,
    activo: str = Form(...),
    user: dict = Depends(require_admin),
    _csrf: bool = Depends(verify_csrf),
):
    if usuario_id == user["id"]:
        return RedirectResponse(
            "/usuarios?error=No podés desactivar tu propia cuenta",
            status_code=303,
        )
    nuevo_estado = activo == "true"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Las cuentas de inquilino se activan/desactivan desde
            # /usuarios/inquilinos, no desde este panel de staff.
            cur.execute(
                "UPDATE usuarios SET activo = %s WHERE id = %s AND rol IN ('admin', 'usuario');",
                (nuevo_estado, usuario_id),
            )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/usuarios?ok=Estado actualizado", status_code=303)
