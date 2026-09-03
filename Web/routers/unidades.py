"""
routers/unidades.py

CRUD completo de la tabla unidades.
"""

import psycopg2
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_connection

router = APIRouter(prefix="/unidades", tags=["unidades"])
templates = Jinja2Templates(directory="templates")

COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "tipo", "label": "Tipo"},
    {"key": "direccion", "label": "Dirección"},
    {"key": "identificador_interno", "label": "Identificador"},
    {"key": "estado", "label": "Estado"},
    {"key": "tiene_gas", "label": "¿Tiene gas?"},
]

FIELDS = [
    {
        "name": "tipo", "label": "Tipo", "type": "select", "required": True,
        "options": [
            {"value": "casa", "label": "Casa"},
            {"value": "local", "label": "Local"},
            {"value": "cochera", "label": "Cochera"},
        ],
    },
    {"name": "direccion", "label": "Dirección", "type": "text", "required": True},
    {"name": "identificador_interno", "label": "Identificador interno", "type": "text", "required": False},
    {
        "name": "estado", "label": "Estado", "type": "select", "required": True,
        "options": [
            {"value": "vacia", "label": "Vacía"},
            {"value": "ocupada", "label": "Ocupada"},
        ],
    },
    {"name": "tiene_gas", "label": "¿Tiene gas?", "type": "checkbox", "required": False},
]


@router.get("")
def listar(request: Request):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM unidades ORDER BY id;")
            rows = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse("list.html", {
        "request": request,
        "title": "Unidades",
        "columns": COLUMNS,
        "rows": rows,
        "base_url": "/unidades",
        "add_url": "/unidades/nuevo",
    })


@router.get("/nuevo")
def form_nuevo(request: Request):
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": "Nueva unidad",
        "fields": FIELDS,
        "values": {},
        "back_url": "/unidades",
    })


@router.post("/nuevo")
def crear(
    tipo: str = Form(...),
    direccion: str = Form(...),
    identificador_interno: str = Form(""),
    estado: str = Form("vacia"),
    tiene_gas: str = Form(None),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unidades (tipo, direccion, identificador_interno, estado, tiene_gas)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (tipo, direccion, identificador_interno or None, estado, bool(tiene_gas)),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse("/unidades/nuevo?error=Ya existe una unidad con ese identificador", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Unidad creada con éxito", status_code=303)


@router.get("/{unidad_id}/editar")
def form_editar(request: Request, unidad_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM unidades WHERE id = %s;", (unidad_id,))
            unidad = cur.fetchone()
    finally:
        conn.close()
    return templates.TemplateResponse("form.html", {
        "request": request,
        "title": f"Editar unidad #{unidad_id}",
        "fields": FIELDS,
        "values": unidad or {},
        "back_url": "/unidades",
    })


@router.post("/{unidad_id}/editar")
def editar(
    unidad_id: int,
    tipo: str = Form(...),
    direccion: str = Form(...),
    identificador_interno: str = Form(""),
    estado: str = Form("vacia"),
    tiene_gas: str = Form(None),
):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE unidades
                SET tipo=%s, direccion=%s, identificador_interno=%s, estado=%s, tiene_gas=%s
                WHERE id=%s;
                """,
                (tipo, direccion, identificador_interno or None, estado, bool(tiene_gas), unidad_id),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return RedirectResponse(f"/unidades/{unidad_id}/editar?error=Ya existe otra unidad con ese identificador", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Unidad actualizada", status_code=303)


@router.post("/{unidad_id}/eliminar")
def eliminar(unidad_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unidades WHERE id = %s;", (unidad_id,))
        conn.commit()
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return RedirectResponse("/unidades?error=No se puede eliminar: tiene contratos o facturas asociadas", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/unidades?ok=Unidad eliminada", status_code=303)