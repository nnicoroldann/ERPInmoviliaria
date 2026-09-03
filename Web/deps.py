"""
deps.py

Piezas compartidas por todos los routers:

- `templates`: única instancia de Jinja2Templates para toda la app,
  con dos funciones globales disponibles en cualquier template:
    * current_user(request) -> dict | None
    * csrf_token(request)   -> str

- Control de acceso:
    * get_current_user  -> exige sesión iniciada (redirige a /login)
    * require_admin     -> exige además rol "admin" (403 si no lo es)

- `verify_csrf`: dependencia para validar el token CSRF en cualquier
  formulario POST (protege contra Cross-Site Request Forgery).
"""

import secrets

from fastapi import Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def _current_user(request: Request):
    return request.session.get("user")


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


# Disponibles dentro de cualquier template: {{ current_user(request) }} / {{ csrf_token(request) }}
templates.env.globals["current_user"] = _current_user
templates.env.globals["csrf_token"] = _csrf_token


class NotAuthenticated(Exception):
    """Se lanza cuando una ruta protegida no tiene sesión iniciada.
    main.py registra un exception_handler que la convierte en un
    redirect a /login."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def get_current_user(request: Request) -> dict:
    """Dependencia: exige que haya una sesión iniciada."""
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated(next_url=request.url.path)
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia: exige sesión iniciada Y rol admin."""
    if user.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="No tenés permiso para realizar esta acción.")
    return user


def require_staff(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia: exige sesión iniciada y rol admin o usuario (personal
    de la inmobiliaria). Bloquea el acceso a las cuentas de inquilino,
    que solo ven su propio portal (/)."""
    if user.get("rol") not in ("admin", "usuario"):
        raise HTTPException(status_code=403, detail="Esta sección es solo para el personal de la inmobiliaria.")
    return user


def verify_csrf(request: Request, csrf_token: str = Form(...)) -> bool:
    """Dependencia: valida el token CSRF enviado por un formulario POST
    contra el guardado en la sesión del usuario."""
    token_sesion = request.session.get("csrf_token")
    if not token_sesion or not secrets.compare_digest(csrf_token, token_sesion):
        raise HTTPException(status_code=403, detail="Token de seguridad inválido o vencido. Recargá la página e intentá de nuevo.")
    return True
