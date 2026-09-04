"""
indices_ajuste.py

Trae valores de los índices que se usan para ajustar el alquiler
(ICL, IPC) de fuentes públicas, los guarda en la tabla valores_indice
(para no pedirlos de nuevo y para poder auditar con qué valor se
calculó cada ajuste), y calcula cuánto le tocaría pagar a un contrato
según el índice que tenga configurado.

Fuentes usadas:

- ICL (Índice para Contratos de Locación): lo publica el BCRA. Se
  pide la lista completa de "variables monetarias" de su API pública
  (https://api.bcra.gob.ar/estadisticas/v3.0/monetarias) y se busca
  la que dice "Contratos de Locación" en la descripción, en vez de
  guardar un número de variable fijo — el BCRA reordena esos números
  de vez en cuando, así que buscarla por texto es más confiable.

- IPC (Índice de Precios al Consumidor / inflación mensual): se pide
  a la API pública de ArgentinaDatos (api.argentinadatos.com), que a
  su vez toma el dato de INDEC. Devuelve la variación mensual (%), y
  para ajustar por IPC lo que se hace es multiplicar los porcentajes
  de todos los meses que pasaron desde el último ajuste (efecto
  "interés compuesto").

- RIPTE: no encontramos una fuente pública con una API estable para
  traerlo automáticamente (a diferencia de ICL e IPC). Los contratos
  que ajustan por RIPTE quedan para carga manual; se explica esto en
  la página de ayuda.

Nada de esto se aplica solo: calcular_ajuste_contrato() solo INFORMA
cuál sería el nuevo monto. El que decide guardarlo es el admin, desde
la pantalla de "Actualizar alquiler" del contrato (dos pasos, como el
resto de la app: primero se muestra el cálculo, después se confirma).

Si la fuente no responde (sin internet, la API está caída, cambió de
formato, etc.) estas funciones devuelven ok=False con un mensaje claro
en vez de romper la página — el admin siempre puede cargar el valor a
mano como alternativa.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import requests

BCRA_LISTA_URL = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias"
BCRA_SERIE_URL = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/{id_variable}"
ARGENTINADATOS_IPC_URL = "https://api.argentinadatos.com/v1/finanzas/indices/inflacion"

RE_DESCRIPCION_ICL = re.compile(r"contratos\s+de\s+locaci[oó]n", re.IGNORECASE)

TIMEOUT = 10

ETIQUETAS_INDICE = {
    "ninguno": "Sin ajuste por índice",
    "icl": "ICL (BCRA)",
    "ipc": "IPC (INDEC / inflación)",
    "ripte": "RIPTE",
}

MESES_PERIODICIDAD = {"trimestral": 3, "semestral": 6, "anual": 12}


def _guardar_valor(conn, indice: str, fecha_valor, valor: float, fuente: str):
    """Guarda (o actualiza) el valor de un índice en una fecha dada.
    No hace commit: queda a cargo de quien llama, para poder meterlo
    en la misma transacción que el resto de la operación."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO valores_indice (indice, fecha, valor, fuente)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (indice, fecha) DO UPDATE SET valor = EXCLUDED.valor, fuente = EXCLUDED.fuente;
            """,
            (indice, fecha_valor, valor, fuente),
        )


def _valor_guardado(conn, indice: str, fecha_valor):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT valor FROM valores_indice WHERE indice = %s AND fecha = %s;",
            (indice, fecha_valor),
        )
        fila = cur.fetchone()
        return float(fila["valor"]) if fila else None


# ---------------------------------------------------------------------------
# ICL (BCRA)
# ---------------------------------------------------------------------------

def _buscar_id_variable_icl():
    resp = requests.get(BCRA_LISTA_URL, timeout=TIMEOUT, verify=True)
    resp.raise_for_status()
    datos = resp.json()
    resultados = datos.get("results", datos if isinstance(datos, list) else [])
    for fila in resultados:
        descripcion = str(fila.get("descripcion", ""))
        if RE_DESCRIPCION_ICL.search(descripcion):
            return fila
    return None


def obtener_icl_actual(conn=None):
    """Devuelve {"ok": True, "valor": float, "fecha": date, "fuente": str}
    con el último valor de ICL publicado por el BCRA, o
    {"ok": False, "error": str} si no se pudo traer."""
    try:
        fila = _buscar_id_variable_icl()
        if not fila:
            return {"ok": False, "error": "El BCRA no publica actualmente una variable identificada como \"Contratos de Locación\"."}
        valor = float(fila["ultValorInformado"])
        fecha_valor = datetime.strptime(fila["ultFechaInformada"], "%Y-%m-%d").date()
        fuente = f"BCRA — {fila.get('descripcion', 'ICL')}"
        if conn is not None:
            _guardar_valor(conn, "icl", fecha_valor, valor, fuente)
        return {"ok": True, "valor": valor, "fecha": fecha_valor, "fuente": fuente}
    except Exception as e:
        return {"ok": False, "error": f"No se pudo traer el ICL del BCRA: {e}"}


def obtener_icl_en_fecha(fecha_objetivo, conn=None):
    """Busca el valor de ICL más cercano a una fecha pasada (para usarlo
    como "ancla" del último ajuste). Devuelve el mismo formato que
    obtener_icl_actual()."""
    guardado = _valor_guardado(conn, "icl", fecha_objetivo) if conn is not None else None
    if guardado is not None:
        return {"ok": True, "valor": guardado, "fecha": fecha_objetivo, "fuente": "BCRA (valor ya guardado)"}
    try:
        fila_variable = _buscar_id_variable_icl()
        if not fila_variable:
            return {"ok": False, "error": "El BCRA no publica actualmente el ICL."}
        id_variable = fila_variable["idVariable"]
        desde = (fecha_objetivo - timedelta(days=6)).isoformat()
        hasta = (fecha_objetivo + timedelta(days=6)).isoformat()
        resp = requests.get(
            BCRA_SERIE_URL.format(id_variable=id_variable),
            params={"desde": desde, "hasta": hasta},
            timeout=TIMEOUT,
            verify=True,
        )
        resp.raise_for_status()
        datos = resp.json()
        resultados = datos.get("results", datos if isinstance(datos, list) else [])
        if not resultados:
            return {"ok": False, "error": f"El BCRA no tiene un valor de ICL cerca del {fecha_objetivo}."}

        def _diferencia(fila):
            fecha_fila = datetime.strptime(fila["fecha"], "%Y-%m-%d").date()
            return abs((fecha_fila - fecha_objetivo).days)

        mas_cercano = min(resultados, key=_diferencia)
        valor = float(mas_cercano["valor"])
        fecha_valor = datetime.strptime(mas_cercano["fecha"], "%Y-%m-%d").date()
        fuente = "BCRA — ICL"
        if conn is not None:
            _guardar_valor(conn, "icl", fecha_valor, valor, fuente)
        return {"ok": True, "valor": valor, "fecha": fecha_valor, "fuente": fuente}
    except Exception as e:
        return {"ok": False, "error": f"No se pudo traer el ICL del {fecha_objetivo} del BCRA: {e}"}


# ---------------------------------------------------------------------------
# IPC (ArgentinaDatos / INDEC)
# ---------------------------------------------------------------------------

def _serie_ipc_mensual():
    resp = requests.get(ARGENTINADATOS_IPC_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    datos = resp.json()
    serie = []
    for fila in datos:
        fecha_fila = datetime.strptime(fila["fecha"][:10], "%Y-%m-%d").date()
        serie.append({"fecha": fecha_fila, "valor": float(fila["valor"])})
    serie.sort(key=lambda f: f["fecha"])
    return serie


def calcular_factor_ipc(fecha_desde, conn=None):
    """Multiplica la inflación mensual (%) publicada desde fecha_desde
    hasta el mes más reciente disponible. Devuelve
    {"ok": True, "factor": float, "meses": int, "fecha": date, "fuente": str}
    (factor 1.15 = subió 15%), o {"ok": False, "error": str}."""
    try:
        serie = _serie_ipc_mensual()
        meses_usados = [f for f in serie if f["fecha"] > fecha_desde]
        if not meses_usados:
            return {"ok": False, "error": "Todavía no hay datos de inflación publicados desde la fecha del último ajuste."}
        factor = 1.0
        for mes in meses_usados:
            factor *= 1 + (mes["valor"] / 100)
            if conn is not None:
                _guardar_valor(conn, "ipc", mes["fecha"], mes["valor"], "ArgentinaDatos / INDEC (variación mensual %)")
        return {
            "ok": True,
            "factor": factor,
            "meses": len(meses_usados),
            "fecha": meses_usados[-1]["fecha"],
            "fuente": "ArgentinaDatos / INDEC",
        }
    except Exception as e:
        return {"ok": False, "error": f"No se pudo traer el IPC: {e}"}


# ---------------------------------------------------------------------------
# Cálculo de ajuste de un contrato
# ---------------------------------------------------------------------------

def proximo_ajuste(contrato) -> date:
    """Fecha en la que corresponde el próximo ajuste, según la
    periodicidad configurada y la fecha del último ajuste."""
    meses = MESES_PERIODICIDAD.get(contrato.get("periodicidad_ajuste"), 12)
    base = contrato.get("fecha_ultimo_ajuste") or contrato.get("fecha_inicio")
    mes_total = base.month - 1 + meses
    anio = base.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(base.day, 28)
    return date(anio, mes, dia)


def calcular_ajuste_contrato(conn, contrato):
    """Calcula cuánto le correspondería pagar a este contrato según su
    índice de ajuste configurado. No modifica nada en la base (además
    de cachear los valores de índice que va trayendo, para no tener
    que volver a pedirlos). Devuelve un dict con "ok" y, si salió
    bien, "nuevo_monto", "detalle" (texto para mostrarle al admin) y
    los datos crudos usados para el cálculo."""
    indice = contrato.get("indice_ajuste", "ninguno")
    monto_base = float(contrato.get("monto_base") or contrato.get("monto_alquiler") or 0)
    fecha_base = contrato.get("fecha_ultimo_ajuste") or contrato.get("fecha_inicio")

    if indice == "ninguno":
        return {"ok": False, "error": "Este contrato no tiene configurado un índice de ajuste."}

    if indice == "ripte":
        return {
            "ok": False,
            "error": (
                "No encontramos una fuente pública con una API estable para traer el RIPTE "
                "automáticamente. Cargá el nuevo valor a mano desde \"Editar contrato\"."
            ),
        }

    if indice == "icl":
        valor_base = obtener_icl_en_fecha(fecha_base, conn=conn)
        if not valor_base["ok"]:
            return valor_base
        valor_actual = obtener_icl_actual(conn=conn)
        if not valor_actual["ok"]:
            return valor_actual
        if valor_base["valor"] <= 0:
            return {"ok": False, "error": "El valor de ICL de la fecha base es 0, no se puede calcular el factor."}
        factor = valor_actual["valor"] / valor_base["valor"]
        nuevo_monto = round(monto_base * factor, 2)
        detalle = (
            f"ICL del {fecha_base.strftime('%d/%m/%Y')}: {valor_base['valor']:.4f} → "
            f"ICL del {valor_actual['fecha'].strftime('%d/%m/%Y')}: {valor_actual['valor']:.4f} "
            f"(factor {factor:.4f}). Fuente: {valor_actual['fuente']}."
        )
        return {
            "ok": True, "nuevo_monto": nuevo_monto, "factor": factor, "detalle": detalle,
            "valor_indice_nuevo": valor_actual["valor"], "fecha_valor_nuevo": valor_actual["fecha"],
        }

    if indice == "ipc":
        resultado = calcular_factor_ipc(fecha_base, conn=conn)
        if not resultado["ok"]:
            return resultado
        nuevo_monto = round(monto_base * resultado["factor"], 2)
        detalle = (
            f"Inflación acumulada desde el {fecha_base.strftime('%d/%m/%Y')} "
            f"({resultado['meses']} mes/es publicados, hasta {resultado['fecha'].strftime('%m/%Y')}): "
            f"{(resultado['factor'] - 1) * 100:.2f}%. Fuente: {resultado['fuente']}."
        )
        return {
            "ok": True, "nuevo_monto": nuevo_monto, "factor": resultado["factor"], "detalle": detalle,
            "valor_indice_nuevo": resultado["factor"], "fecha_valor_nuevo": resultado["fecha"],
        }

    return {"ok": False, "error": f"Índice de ajuste desconocido: {indice}"}
