"""
main.py

Punto de entrada de la aplicación web del ERP Inmobiliarias.

Para correrlo:
    uvicorn main:app --reload

Y abrís en el navegador: http://127.0.0.1:8000

Seguridad:
- Requiere SECRET_KEY en el .env (usada para firmar la cookie de sesión).
- Sesión vía cookie firmada (SessionMiddleware), no hay tokens en la URL.
- Cabeceras de seguridad básicas en cada respuesta.
- ENTORNO=produccion en el .env activa cookies "secure" (solo HTTPS) y HSTS.
"""

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from database import get_connection
from deps import NotAuthenticated, get_current_user, templates
from routers import (
    auth,
    clientes,
    contratos,
    cuotas,
    factura,
    factura_agua,
    inquilinos,
    propietarios,
    unidades,
    usuarios,
)

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "Falta SECRET_KEY en el archivo .env. Generá una y agregala, por ejemplo:\n"
        '  python3 -c "import secrets; print(secrets.token_hex(32))"\n'
        "y pegá el resultado como SECRET_KEY=... en Web/.env"
    )

ENTORNO = os.getenv("ENTORNO", "desarrollo").strip().lower()
COOKIE_SEGURA = ENTORNO == "produccion"

app = FastAPI(title="ERP Inmobiliarias")

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="erp_session",
    same_site="lax",
    https_only=COOKIE_SEGURA,
    max_age=60 * 60 * 8,  # la sesión dura 8 horas
)


@app.middleware("http")
async def cabeceras_de_seguridad(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if COOKIE_SEGURA:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")

# Rutas de autenticación primero, después el resto de módulos del ERP.
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(inquilinos.router)
app.include_router(clientes.router)
app.include_router(propietarios.router)
app.include_router(unidades.router)
app.include_router(contratos.router)
app.include_router(cuotas.router)
app.include_router(factura.router)
app.include_router(factura_agua.router)


@app.exception_handler(NotAuthenticated)
async def manejar_no_autenticado(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url=f"/login?next={exc.next_url}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def manejar_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 403:
        return templates.TemplateResponse("403.html", {"request": request}, status_code=403)
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _obtener_estadisticas() -> dict:
    """Números rápidos para la portada. Si algo falla (por ejemplo,
    una tabla vacía o un problema de conexión momentáneo) se muestran
    ceros en vez de romper la página de inicio."""
    stats = {
        "clientes_activos": 0,
        "propietarios_total": 0,
        "unidades_total": 0,
        "unidades_ocupadas": 0,
        "contratos_activos": 0,
        "cuotas_pendientes": 0,
    }
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM clientes WHERE estado = 'activo';")
                stats["clientes_activos"] = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) AS total FROM propietarios WHERE estado = 'activo';")
                stats["propietarios_total"] = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) AS total FROM unidades;")
                stats["unidades_total"] = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) AS total FROM unidades WHERE estado = 'ocupada';")
                stats["unidades_ocupadas"] = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) AS total FROM contratos WHERE estado = 'activo';")
                stats["contratos_activos"] = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) AS total FROM cuotas WHERE estado = 'pendiente';")
                stats["cuotas_pendientes"] = cur.fetchone()["total"]
        finally:
            conn.close()
    except Exception:
        pass
    return stats


def _deuda(filas, campo_estado="estado", estados_deuda=("pendiente", "vencido", "parcial")):
    """Suma el monto de las filas (cuotas o facturas) que todavía se deben."""
    return sum(
        (f["monto"] for f in filas if f.get(campo_estado) in estados_deuda),
        start=0,
    )


def _datos_inquilino(cliente_id) -> dict:
    """Reúne todo lo que un inquilino ve en su portal ("/"): sus datos de
    cliente, su(s) contrato(s) con la unidad y, para cada uno, el
    historial y la deuda de cuotas de alquiler, gas y agua."""
    datos = {"cliente": None, "contratos": []}
    if not cliente_id:
        return datos
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes WHERE id = %s;", (cliente_id,))
            datos["cliente"] = cur.fetchone()

            cur.execute(
                """
                SELECT co.*, un.tipo, un.direccion, un.identificador_interno, un.tiene_gas
                FROM contratos co
                JOIN unidades un ON un.id = co.unidad_id
                WHERE co.cliente_id = %s
                ORDER BY (co.estado = 'activo') DESC, co.id DESC;
                """,
                (cliente_id,),
            )
            contratos = cur.fetchall()

            for contrato in contratos:
                cur.execute(
                    "SELECT * FROM cuotas WHERE contrato_id = %s ORDER BY mes DESC;",
                    (contrato["id"],),
                )
                contrato["cuotas"] = cur.fetchall()
                contrato["deuda_alquiler"] = _deuda(contrato["cuotas"])

                cur.execute(
                    "SELECT * FROM facturas_gas WHERE unidad_id = %s ORDER BY periodo DESC;",
                    (contrato["unidad_id"],),
                )
                contrato["facturas_gas"] = cur.fetchall()
                contrato["deuda_gas"] = _deuda(contrato["facturas_gas"], estados_deuda=("pendiente", "vencido"))

                cur.execute(
                    "SELECT * FROM facturas_agua WHERE unidad_id = %s ORDER BY periodo DESC;",
                    (contrato["unidad_id"],),
                )
                contrato["facturas_agua"] = cur.fetchall()
                contrato["deuda_agua"] = _deuda(contrato["facturas_agua"], estados_deuda=("pendiente", "vencido"))

            datos["contratos"] = contratos
    finally:
        conn.close()
    return datos


@app.get("/")
def home(request: Request, user: dict = Depends(get_current_user)):
    if user.get("rol") == "inquilino":
        return templates.TemplateResponse("mi_cuenta.html", {
            "request": request,
            "datos": _datos_inquilino(user.get("cliente_id")),
        })
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": _obtener_estadisticas(),
    })
