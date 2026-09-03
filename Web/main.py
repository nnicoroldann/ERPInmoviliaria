"""
main.py

Punto de entrada de la aplicación web del mini-ERP de alquileres.

Para correrlo:
    uvicorn main:app --reload

Y abrís en el navegador: http://127.0.0.1:8000
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from routers import clientes, unidades, contratos, cuotas, factura

app = FastAPI(title="Mini-ERP de Alquileres")

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

app.include_router(clientes.router)
app.include_router(unidades.router)
app.include_router(contratos.router)
app.include_router(cuotas.router)
app.include_router(factura.router)


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})