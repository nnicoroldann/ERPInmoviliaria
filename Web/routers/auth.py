"""
routers/auth.py

Registro, login y logout.

Reglas de negocio:
- El primer usuario que se registra en todo el sistema queda como
  "admin" automáticamente. Todos los siguientes quedan como "usuario".
  Un admin puede ascender/descender roles después desde /usuarios.
- Las contraseñas se guardan siempre con hash bcrypt (security.py).
- El login tiene un límite simple de intentos fallidos por
  IP + usuario para dificultar ataques de fuerza bruta.
"""

import re
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from database import get_connection
from deps import templates, verify_csrf
from security import hash_password, verify_password

router = APIRouter(tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- límite de intentos de login (en memoria, simple pero efectivo) ---
MAX_INTENTOS = 5
VENTANA_SEGUNDOS = 15 * 60
_intentos_fallidos: dict[str, list[float]] = {}


def _demasiados_intentos(clave: str) -> bool:
    ahora = time.time()
    vigentes = [t for t in _intentos_fallidos.get(clave, []) if ahora - t < VENTANA_SEGUNDOS]
    _intentos_fallidos[clave] = vigentes
    return len(vigentes) >= MAX_INTENTOS


def _registrar_intento_fallido(clave: str) -> None:
    _intentos_fallidos.setdefault(clave, []).append(time.time())


def _limpiar_intentos(clave: str) -> None:
    _intentos_fallidos.pop(clave, None)


def _contar_usuarios(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM usuarios;")
        return cur.fetchone()["total"]


def _buscar_usuario(conn, identificador: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM usuarios WHERE email = %s OR LOWER(nombre_usuario) = %s;",
            (identificador, identificador),
        )
        return cur.fetchone()


def _sesion_de(usuario: dict) -> dict:
    return {
        "id": usuario["id"],
        "nombre_usuario": usuario["nombre_usuario"],
        "email": usuario["email"],
        "rol": usuario["rol"],
        # Solo tiene valor para cuentas de inquilino: es el cliente al que
        # está vinculada la cuenta, y es lo que usa main.py para mostrarle
        # únicamente su propia unidad en "/".
        "cliente_id": usuario.get("cliente_id"),
    }


# ------------------------------------------------------------------
# Registro
# ------------------------------------------------------------------

@router.get("/registro")
def form_registro(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("registro.html", {"request": request, "values": {}})


@router.post("/registro")
def registro(
    request: Request,
    nombre_usuario: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    _csrf: bool = Depends(verify_csrf),
):
    nombre_usuario = nombre_usuario.strip()
    email = email.strip().lower()

    errores = []
    if len(nombre_usuario) < 3 or len(nombre_usuario) > 50:
        errores.append("El nombre de usuario debe tener entre 3 y 50 caracteres.")
    if not EMAIL_RE.match(email):
        errores.append("El email no es válido.")
    if len(password) < 8:
        errores.append("La contraseña debe tener al menos 8 caracteres.")
    if password != password2:
        errores.append("Las contraseñas no coinciden.")

    if errores:
        return templates.TemplateResponse("registro.html", {
            "request": request,
            "error": " ".join(errores),
            "values": {"nombre_usuario": nombre_usuario, "email": email},
        }, status_code=400)

    conn = get_connection()
    try:
        es_primero = _contar_usuarios(conn) == 0
        rol = "admin" if es_primero else "usuario"
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarios (nombre_usuario, email, password_hash, rol)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, nombre_usuario, email, rol;
                    """,
                    (nombre_usuario, email, hash_password(password), rol),
                )
                nuevo = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            return templates.TemplateResponse("registro.html", {
                "request": request,
                "error": "Ya existe una cuenta con ese nombre de usuario o email.",
                "values": {"nombre_usuario": nombre_usuario, "email": email},
            }, status_code=400)
    finally:
        conn.close()

    request.session["user"] = _sesion_de(nuevo)
    if es_primero:
        mensaje = "Cuenta creada. Sos el primer usuario del sistema, así que quedaste como administrador."
    else:
        mensaje = "Cuenta creada con éxito."
    return RedirectResponse(f"/?ok={mensaje}", status_code=303)


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------

@router.get("/login")
def form_login(request: Request, next: str = "/"):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "next": next})


@router.post("/login")
def login(
    request: Request,
    identificador: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    _csrf: bool = Depends(verify_csrf),
):
    identificador_norm = identificador.strip().lower()
    clave = f"{request.client.host if request.client else 'desconocido'}:{identificador_norm}"

    if _demasiados_intentos(clave):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Demasiados intentos fallidos. Esperá unos minutos y volvé a intentar.",
            "next": next,
        }, status_code=429)

    conn = get_connection()
    try:
        usuario = _buscar_usuario(conn, identificador_norm)
    finally:
        conn.close()

    credenciales_validas = usuario and verify_password(password, usuario["password_hash"])

    if not credenciales_validas:
        _registrar_intento_fallido(clave)
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Usuario/email o contraseña incorrectos.",
            "next": next,
        }, status_code=401)

    if not usuario["activo"]:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Tu cuenta está desactivada. Consultá con un administrador.",
            "next": next,
        }, status_code=403)

    _limpiar_intentos(clave)
    request.session["user"] = _sesion_de(usuario)
    destino = next if next.startswith("/") else "/"
    return RedirectResponse(destino, status_code=303)


# ------------------------------------------------------------------
# Logout
# ------------------------------------------------------------------

@router.post("/logout")
def logout(request: Request, _csrf: bool = Depends(verify_csrf)):
    request.session.clear()
    return RedirectResponse("/login?ok=Sesión cerrada", status_code=303)
