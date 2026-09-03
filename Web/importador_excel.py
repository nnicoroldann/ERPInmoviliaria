"""
importador_excel.py

Lee el Excel de control de la inmobiliaria (inquilinos, dueños,
cocheras, gas, teléfonos) y arma un "plan" de qué hay que cargar en
la base — sin tocar todavía nada — para poder mostrárselo a un admin
antes de confirmar. Una vez confirmado, aplicar_plan() hace todos los
INSERT/UPDATE en una sola transacción.

Cómo está armado el Excel real de la inmobiliaria (y cómo se lee):

- Hojas que empiezan con "ALQUILERES" (puede haber varias, una por
  período: "ALQUILERES 2025-2026", "ALQUILERES 2027-2028", etc.):
  columna A = inquilino, columna B = dueño/propietario, y desde la
  columna C en adelante, una columna por mes (el encabezado de la
  fila 1 es una fecha) con el estado de ese mes: "PAGO", guiones
  (no pagó), "DEBE", etc.

- Hoja "COCHERAS": mismo formato pero sin columna de dueño (son
  cocheras que se alquilan aparte).

- Hoja "GAS": columna A = inquilino, B = dueño, C = N° de cuenta de
  gas, y desde la D en adelante una columna por mes CON EL NOMBRE
  del mes (ENERO, FEBRERO, ...) en vez de una fecha — el Excel no
  dice de qué año, así que se asume el año actual (queda avisado en
  el plan para que el admin lo revise).

- Hoja "TELEFONOS": columna A = inquilino, columna B = teléfono. Solo
  se usa para completar el teléfono de clientes que ya se identificaron
  en otra hoja; no se crean clientes nuevos solo por aparecer acá.

- Cualquier otra hoja (AUMENTOS, ARREGLOS, COOPERATIVA ELECTRICA,
  BACKUP FINAL 2024, o lo que sea que tenga un nombre distinto) se
  ignora.

Cosas que el Excel NO tiene y hay que inventar con un placeholder
bien visible (para que el admin las complete después desde las
pantallas normales de Clientes / Unidades / Contratos, que ya
permiten editar todo):

- DNI/CUIT del cliente -> "PENDIENTE-00001", "PENDIENTE-00002", ...
- Dirección de la unidad -> texto placeholder que incluye el nombre
  del inquilino y la hoja de origen, para poder ubicarla después.
- Monto del alquiler / de la factura de gas -> 0.

Nada de esto se pierde entre subidas: cada fila del Excel genera un
"identificador_interno" fijo para su unidad (por ejemplo
"EXCEL:ALQUILERES-2025-2026:14"), así que si el admin sube el mismo
Excel de nuevo (o una versión más nueva con más meses cargados) no se
duplican clientes/unidades/contratos: se reconoce lo que ya estaba y
solo se agregan las cuotas o facturas de gas que todavía no existían.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# openpyxl solo se necesita para el tipo de wb que llega desde el
# router; no se importa acá para no obligar a tenerlo instalado si
# alguna vez se corre este módulo aislado (el router es el que hace
# `import openpyxl` y carga el workbook).

RE_HOJA_ALQUILERES = re.compile(r"^ALQUILERES", re.IGNORECASE)
RE_HOJA_COCHERAS = re.compile(r"COCHERA", re.IGNORECASE)
RE_HOJA_GAS = re.compile(r"^GAS\b", re.IGNORECASE)
RE_HOJA_TELEFONOS = re.compile(r"TELEFONO", re.IGNORECASE)

MESES_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10,
    "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

PLACEHOLDER_DIRECCION = "Dirección sin especificar (completar)"


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def normalizar(texto):
    """minúsculas, sin acentos, solo letras/números/espacios (para comparar
    nombres que en el Excel están escritos con mayúsculas/tildes/espacios
    distintos según la hoja)."""
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def compacta(texto):
    """Igual que normalizar() pero sin espacios, para tolerar cosas
    como "Bu zey" / "Buzey"."""
    return normalizar(texto).replace(" ", "")


def dividir_nombre(raw):
    """
    En el Excel el inquilino/dueño casi siempre viene como
    "Apellido Nombre" (a veces solo el apellido, a veces un nombre de
    empresa). No hay forma 100% confiable de separar apellido y
    nombre en español, así que esto es best-effort: el admin puede
    corregirlo después desde Clientes/Propietarios, igual que
    cualquier otro dato de este importador.
    """
    texto = (raw or "").strip()
    partes = texto.split()
    if len(partes) >= 2:
        apellido, nombre = partes[0], " ".join(partes[1:])
    elif len(partes) == 1:
        apellido, nombre = partes[0], "(completar)"
    else:
        apellido, nombre = "(sin datos)", "(completar)"
    return apellido.strip().title(), nombre.strip().title()


def _texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def _clasificar_pago(valor):
    """
    Interpreta una celda de "estado de pago" del Excel. Devuelve
    (estado, nota) donde estado es 'pagado' / 'pendiente' / 'parcial',
    o None si la celda no aplica (vacía = ese mes no corresponde,
    antes o después del contrato).

    Tolera errores de tipeo típicos de una planilla cargada a mano
    durante años (PAGO/PAGADO/PAGI, DEBE/DB, guiones como marca de
    "no pagó", etc). Lo que no se reconoce con certeza se guarda como
    "pendiente" con el texto original a la vista en vez de perderlo o
    adivinar mal.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return ("pendiente", f"Valor en el Excel: {valor}")
    texto = _texto(valor)
    if not texto:
        return None
    if re.fullmatch(r"[-_\s]+", texto):
        return ("pendiente", None)
    plano = texto.upper()
    if plano.startswith("PAG"):
        return ("pagado", None)
    if "DEBE" in plano or plano in ("DB", "D B") or "RESTO" in plano or "RESTA" in plano:
        return ("pendiente", texto)
    if "CTA" in plano or "FAVOR" in plano or "SEÑA" in plano or "SENA" in plano or "CUENTA" in plano:
        return ("parcial", texto)
    return ("pendiente", texto)


def _mes_iso(fecha):
    return f"{fecha.year:04d}-{fecha.month:02d}"


def _leer_fecha_celda(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _formatear_cuenta(valor):
    if valor is None:
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    texto = _texto(valor)
    return texto or None


def _codigo_hoja(hoja):
    codigo = re.sub(r"[^A-Za-z0-9]+", "-", hoja.strip()).strip("-").upper()
    return codigo[:24] or "HOJA"


def _primer_apellido_normalizado(raw):
    partes = (raw or "").split()
    return normalizar(partes[0]) if partes else ""


# ---------------------------------------------------------------------------
# Contexto: junta lo que ya existe en la base y lo que se va agregando
# a medida que se recorren las hojas del Excel.
# ---------------------------------------------------------------------------

class ContextoImportacion:
    def __init__(self, conn):
        self.conn = conn

        self.clientes_por_nombre = {}     # norm o compacta -> id existente
        self.propietarios_por_nombre = {}

        self.identificadores_existentes = set()

        self.clientes_nuevos = {}         # clave normalizada -> datos a insertar
        self.propietarios_nuevos = {}
        self.unidades = []                # una entrada por cada fila de ALQUILERES/COCHERAS
        self.unidades_por_cliente = {}    # clave cliente -> [índices en self.unidades]
        self.unidad_alquiler_por_cliente = {}  # clave cliente -> índice de su unidad "casa/local" (para fusionar entre hojas ALQUILERES de distintos períodos)
        self.unidades_por_par = {}        # (apellido_inquilino, apellido_dueño) -> [índices]
        self.telefonos_a_actualizar = []
        self.avisos = []

        self._contador_clientes = 0

        self._cargar_existentes()

    def _cargar_existentes(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, nombre, apellido FROM clientes;")
            for fila in cur.fetchall():
                self._indexar_persona(fila, self.clientes_por_nombre)

            cur.execute("SELECT id, nombre, apellido FROM propietarios;")
            for fila in cur.fetchall():
                self._indexar_persona(fila, self.propietarios_por_nombre)

            cur.execute("SELECT identificador_interno FROM unidades WHERE identificador_interno IS NOT NULL;")
            self.identificadores_existentes = {f["identificador_interno"] for f in cur.fetchall()}

            cur.execute("SELECT dni_cuit FROM clientes WHERE dni_cuit LIKE 'PENDIENTE-%%';")
            maximo = 0
            for fila in cur.fetchall():
                m = re.fullmatch(r"PENDIENTE-(\d+)", fila["dni_cuit"] or "")
                if m:
                    maximo = max(maximo, int(m.group(1)))
            self._contador_clientes = maximo

    @staticmethod
    def _indexar_persona(fila, mapa):
        nombre, apellido = fila["nombre"] or "", fila["apellido"] or ""
        claves = {
            normalizar(f"{apellido} {nombre}"), normalizar(f"{nombre} {apellido}"),
            compacta(f"{apellido} {nombre}"), compacta(f"{nombre} {apellido}"),
        }
        for clave in claves:
            if clave:
                mapa.setdefault(clave, fila["id"])

    # -- resolución de personas ------------------------------------------------

    def resolver_cliente(self, raw_nombre, hoja, fila_excel):
        norm = normalizar(raw_nombre)
        if not norm:
            return None
        comp = compacta(raw_nombre)
        for clave in (norm, comp):
            if clave in self.clientes_por_nombre:
                return ("db", self.clientes_por_nombre[clave])
        if norm in self.clientes_nuevos:
            return ("nuevo", norm)

        apellido, nombre = dividir_nombre(raw_nombre)
        self._contador_clientes += 1
        self.clientes_nuevos[norm] = {
            "nombre": nombre,
            "apellido": apellido,
            "dni_cuit": f"PENDIENTE-{self._contador_clientes:05d}",
            "telefono": None,
            "email": None,
            "estado": "activo",
            "origen": f"{hoja} fila {fila_excel}",
        }
        return ("nuevo", norm)

    def resolver_propietario(self, raw_nombre, hoja, fila_excel):
        if not raw_nombre or not raw_nombre.strip():
            return None
        norm = normalizar(raw_nombre)
        comp = compacta(raw_nombre)
        for clave in (norm, comp):
            if clave in self.propietarios_por_nombre:
                return ("db", self.propietarios_por_nombre[clave])
        if norm in self.propietarios_nuevos:
            return ("nuevo", norm)

        apellido, nombre = dividir_nombre(raw_nombre)
        self.propietarios_nuevos[norm] = {
            "nombre": nombre,
            "apellido": apellido,
            "dni_cuit": None,
            "telefono": None,
            "email": None,
            "cbu_alias": None,
            "estado": "activo",
            "origen": f"{hoja} fila {fila_excel}",
        }
        return ("nuevo", norm)

    def identificador(self, codigo_hoja, fila_excel):
        return f"EXCEL:{codigo_hoja}:{fila_excel}"

    def registrar_unidad(self, unidad, cliente_clave, dueño_raw, inquilino_raw):
        indice = len(self.unidades)
        self.unidades.append(unidad)
        if cliente_clave:
            self.unidades_por_cliente.setdefault(cliente_clave, []).append(indice)
        apellido_inq = _primer_apellido_normalizado(inquilino_raw)
        apellido_dueño = _primer_apellido_normalizado(dueño_raw)
        self.unidades_por_par.setdefault((apellido_inq, apellido_dueño), []).append(indice)
        return indice


# ---------------------------------------------------------------------------
# Lectura de cada tipo de hoja
# ---------------------------------------------------------------------------

def _leer_hoja_alquileres_o_cocheras(ws, hoja, ctx, es_cochera):
    codigo_hoja = _codigo_hoja(hoja)
    col_inquilino, col_dueño = 1, (None if es_cochera else 2)
    col_primer_mes = 2 if es_cochera else 3

    encabezado = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    columnas_mes = [
        (c, _leer_fecha_celda(encabezado[c - 1]))
        for c in range(col_primer_mes, ws.max_column + 1)
        if _leer_fecha_celda(encabezado[c - 1])
    ]
    if not columnas_mes:
        ctx.avisos.append(f"Hoja '{hoja}': no se encontraron columnas de mes con fecha válida en la fila 1, se ignoró toda la hoja.")
        return

    for fila in range(2, ws.max_row + 1):
        inquilino_raw = _texto(ws.cell(row=fila, column=col_inquilino).value)
        if not inquilino_raw:
            continue
        dueño_raw = _texto(ws.cell(row=fila, column=col_dueño).value) if col_dueño else ""

        identificador = ctx.identificador(codigo_hoja, fila)
        cliente_clave = ctx.resolver_cliente(inquilino_raw, hoja, fila)
        propietario_clave = ctx.resolver_propietario(dueño_raw, hoja, fila) if dueño_raw else None

        if es_cochera and propietario_clave is None:
            # Las cocheras no traen dueño en el Excel: si el mismo inquilino
            # ya tiene otra unidad con dueño conocido, se lo asignamos también
            # a la cochera (es una heurística, se puede corregir a mano).
            for idx in ctx.unidades_por_cliente.get(cliente_clave, []):
                candidato = ctx.unidades[idx].get("propietario_clave")
                if candidato:
                    propietario_clave = candidato
                    break

        cuotas = []
        fechas_con_dato = []
        for col, fecha_col in columnas_mes:
            resultado = _clasificar_pago(ws.cell(row=fila, column=col).value)
            if resultado is None:
                continue
            estado, nota = resultado
            fechas_con_dato.append(fecha_col)
            cuotas.append({"mes": _mes_iso(fecha_col), "estado": estado, "comprobante": nota})

        if fechas_con_dato:
            fecha_inicio, fecha_fin = min(fechas_con_dato), max(fechas_con_dato)
        else:
            fecha_inicio = min(f for _, f in columnas_mes)
            fecha_fin = max(f for _, f in columnas_mes)
            ctx.avisos.append(
                f"Hoja '{hoja}' fila {fila} ({inquilino_raw}): no tiene ningún mes cargado; "
                "se creó el contrato igual, sin cuotas. Revisá las fechas."
            )

        # Si el mismo inquilino ya tiene una unidad de alquiler (no cochera)
        # cargada desde OTRA hoja de ALQUILERES de este mismo Excel (por
        # ejemplo "ALQUILERES 2025-2026" y "ALQUILERES 2027-2028": son
        # períodos distintos del mismo contrato), no creamos una segunda
        # unidad — fusionamos las cuotas nuevas en la que ya existe.
        indice_previo = None if es_cochera else ctx.unidad_alquiler_por_cliente.get(cliente_clave)
        if indice_previo is not None:
            unidad_previa = ctx.unidades[indice_previo]
            contrato_previo = unidad_previa["contrato"]
            meses_ya = {c["mes"] for c in contrato_previo["cuotas"]}
            for cuota in cuotas:
                if cuota["mes"] not in meses_ya:
                    contrato_previo["cuotas"].append(cuota)
                    meses_ya.add(cuota["mes"])
            if fecha_inicio.isoformat() < contrato_previo["fecha_inicio"]:
                contrato_previo["fecha_inicio"] = fecha_inicio.isoformat()
                contrato_previo["dia_vencimiento"] = fecha_inicio.day
            if fecha_fin.isoformat() > contrato_previo["fecha_fin"]:
                contrato_previo["fecha_fin"] = fecha_fin.isoformat()
            if propietario_clave and unidad_previa.get("propietario_clave") not in (None, propietario_clave):
                ctx.avisos.append(
                    f"Hoja '{hoja}' fila {fila} ({inquilino_raw}): el dueño ('{dueño_raw}') no coincide "
                    "con el que ya se había cargado para este mismo inquilino en otra hoja. Revisar a mano."
                )
            unidad_previa["origen"] += f"; también en {hoja} fila {fila}"
            continue

        unidad = {
            "identificador_interno": identificador,
            "tipo": "cochera" if es_cochera else "casa",
            "direccion": f"{PLACEHOLDER_DIRECCION} — inquilino: {inquilino_raw} (hoja: {hoja})",
            "tiene_gas": False,
            "gas_cuenta": None,
            "propietario_clave": propietario_clave,
            "cliente_clave": cliente_clave,
            "origen": f"{hoja} fila {fila}",
            "es_nueva_estim": identificador not in ctx.identificadores_existentes,
            "contrato": {
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_fin": fecha_fin.isoformat(),
                "monto_alquiler": 0,
                "dia_vencimiento": fecha_inicio.day,
                "cuotas": cuotas,
            },
        }
        indice_nuevo = ctx.registrar_unidad(unidad, cliente_clave, dueño_raw, inquilino_raw)
        if not es_cochera:
            ctx.unidad_alquiler_por_cliente[cliente_clave] = indice_nuevo


def _leer_hoja_gas(ws, hoja, ctx):
    encabezado = [_texto(ws.cell(row=1, column=c).value).upper() for c in range(1, ws.max_column + 1)]
    columnas_mes = []
    for c in range(4, ws.max_column + 1):
        nombre_mes = encabezado[c - 1].strip() if c - 1 < len(encabezado) else ""
        if nombre_mes in MESES_ES:
            columnas_mes.append((c, MESES_ES[nombre_mes]))
    if not columnas_mes:
        ctx.avisos.append(f"Hoja '{hoja}': no se reconocieron columnas de mes (ENERO, FEBRERO, ...), se ignoró la hoja.")
        return

    anio_asumido = date.today().year
    ctx.avisos.append(
        f"Hoja '{hoja}': las columnas de mes no indican el año, se asumió {anio_asumido}. "
        "Revisá los períodos de las facturas de gas que se cargaron."
    )

    for fila in range(2, ws.max_row + 1):
        inquilino_raw = _texto(ws.cell(row=fila, column=1).value)
        if not inquilino_raw:
            continue
        dueño_raw = _texto(ws.cell(row=fila, column=2).value)
        cuenta = _formatear_cuenta(ws.cell(row=fila, column=3).value)

        clave_par = (_primer_apellido_normalizado(inquilino_raw), _primer_apellido_normalizado(dueño_raw))
        candidatos = ctx.unidades_por_par.get(clave_par, [])

        unidad_idx = None
        for idx in candidatos:
            u = ctx.unidades[idx]
            if u["tipo"] == "cochera":
                continue
            if u.get("gas_cuenta") in (None, cuenta):
                unidad_idx = idx
                break

        if unidad_idx is None:
            if candidatos:
                ctx.avisos.append(
                    f"Hoja '{hoja}' fila {fila}: '{inquilino_raw}' (dueño: {dueño_raw or 's/d'}) ya "
                    f"tiene otra cuenta de gas asignada; no se cargó la cuenta {cuenta or 's/d'} "
                    "para no pisarla. Revisalo a mano en Unidades."
                )
            else:
                ctx.avisos.append(
                    f"Hoja '{hoja}' fila {fila}: no se encontró una unidad de alquiler para "
                    f"'{inquilino_raw}' (dueño: {dueño_raw or 's/d'}, cuenta {cuenta or 's/d'}). "
                    "No se cargó la factura de gas; se puede asociar a mano desde Unidades / Facturas de gas."
                )
            continue

        unidad = ctx.unidades[unidad_idx]
        unidad["tiene_gas"] = True
        if cuenta:
            unidad["gas_cuenta"] = cuenta

        facturas = unidad.setdefault("facturas_gas", [])
        periodos_ya = {f["periodo"] for f in facturas}
        for col, mes_num in columnas_mes:
            resultado = _clasificar_pago(ws.cell(row=fila, column=col).value)
            if resultado is None:
                continue
            estado, _nota = resultado
            periodo = f"{anio_asumido:04d}-{mes_num:02d}"
            if periodo in periodos_ya:
                continue
            facturas.append({"periodo": periodo, "estado": estado, "monto": 0})
            periodos_ya.add(periodo)


def _leer_hoja_telefonos(ws, hoja, ctx):
    for fila in range(2, ws.max_row + 1):
        inquilino_raw = _texto(ws.cell(row=fila, column=1).value)
        telefono_raw = _texto(ws.cell(row=fila, column=2).value)
        if not inquilino_raw or not telefono_raw:
            continue
        norm = normalizar(inquilino_raw)
        comp = compacta(inquilino_raw)

        if norm in ctx.clientes_nuevos:
            if not ctx.clientes_nuevos[norm].get("telefono"):
                ctx.clientes_nuevos[norm]["telefono"] = telefono_raw
            continue

        cliente_id = None
        for clave in (norm, comp):
            if clave in ctx.clientes_por_nombre:
                cliente_id = ctx.clientes_por_nombre[clave]
                break
        if cliente_id is None:
            continue  # no se crean clientes nuevos solo por la agenda de teléfonos
        ctx.telefonos_a_actualizar.append({"cliente_id": cliente_id, "telefono": telefono_raw})


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def construir_plan(wb, conn):
    """
    Recorre todas las hojas del workbook (ya abierto con openpyxl) y
    arma el plan de importación. No escribe nada en la base: solo
    hace SELECTs para saber qué ya existe.
    """
    ctx = ContextoImportacion(conn)
    hojas_leidas, hojas_ignoradas = [], []

    for hoja in wb.sheetnames:
        ws = wb[hoja]
        if RE_HOJA_ALQUILERES.search(hoja):
            _leer_hoja_alquileres_o_cocheras(ws, hoja, ctx, es_cochera=False)
            hojas_leidas.append(hoja)
        elif RE_HOJA_COCHERAS.search(hoja):
            _leer_hoja_alquileres_o_cocheras(ws, hoja, ctx, es_cochera=True)
            hojas_leidas.append(hoja)
        elif RE_HOJA_GAS.search(hoja.strip()):
            _leer_hoja_gas(ws, hoja, ctx)
            hojas_leidas.append(hoja)
        elif RE_HOJA_TELEFONOS.search(hoja):
            _leer_hoja_telefonos(ws, hoja, ctx)
            hojas_leidas.append(hoja)
        else:
            hojas_ignoradas.append(hoja)

    if any(u.get("contrato", {}).get("monto_alquiler") == 0 for u in ctx.unidades if u.get("contrato")):
        ctx.avisos.append(
            "El Excel no incluye montos de alquiler: todos los contratos se cargaron con $0. "
            "Hace falta completarlos a mano desde Contratos."
        )
    if any(u.get("facturas_gas") for u in ctx.unidades):
        ctx.avisos.append(
            "Las facturas de gas se cargaron sin monto ($0) porque el Excel no lo incluye; "
            "completalas a mano desde Facturas de gas."
        )

    unidades_nuevas = sum(1 for u in ctx.unidades if u.get("es_nueva_estim"))
    total_cuotas = sum(len(u["contrato"]["cuotas"]) for u in ctx.unidades if u.get("contrato"))
    total_facturas_gas = sum(len(u.get("facturas_gas", [])) for u in ctx.unidades)

    plan = {
        "clientes_nuevos": ctx.clientes_nuevos,
        "propietarios_nuevos": ctx.propietarios_nuevos,
        "unidades": ctx.unidades,
        "telefonos_a_actualizar": ctx.telefonos_a_actualizar,
        "avisos": ctx.avisos,
        "resumen": {
            "hojas_leidas": hojas_leidas,
            "hojas_ignoradas": hojas_ignoradas,
            "clientes_nuevos": len(ctx.clientes_nuevos),
            "propietarios_nuevos": len(ctx.propietarios_nuevos),
            "unidades_nuevas_estimadas": unidades_nuevas,
            "unidades_a_revisar_estimadas": len(ctx.unidades) - unidades_nuevas,
            "cuotas_a_cargar_estimadas": total_cuotas,
            "facturas_gas_a_cargar_estimadas": total_facturas_gas,
            "telefonos_a_actualizar_estimados": len(ctx.telefonos_a_actualizar),
            "avisos": len(ctx.avisos),
        },
    }
    return plan


def aplicar_plan(conn, plan):
    """
    Aplica el plan en una única transacción (todo o nada). Usa
    ON CONFLICT DO NOTHING en unidades/cuotas/facturas_gas para que
    subir el mismo Excel (o una versión más nueva) dos veces no
    duplique nada: lo que ya existe se reconoce por su
    identificador_interno / (contrato, mes) / (unidad, período), y
    solo se agrega lo que falta.

    Devuelve un resumen con lo que efectivamente se creó (puede ser
    menor a la previsualización si parte de los datos ya se habían
    cargado antes).
    """
    resultado = {
        "clientes_creados": 0,
        "propietarios_creados": 0,
        "unidades_creadas": 0,
        "contratos_creados": 0,
        "cuotas_creadas": 0,
        "facturas_gas_creadas": 0,
        "telefonos_actualizados": 0,
    }

    ids_clientes = {}
    ids_propietarios = {}

    def id_de(clave, mapa):
        if clave is None:
            return None
        origen, valor = clave
        return valor if origen == "db" else mapa.get(valor)

    with conn.cursor() as cur:
        for clave, datos in plan["clientes_nuevos"].items():
            cur.execute(
                """
                INSERT INTO clientes (nombre, apellido, dni_cuit, telefono, email, estado)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (datos["nombre"], datos["apellido"], datos["dni_cuit"],
                 datos.get("telefono"), datos.get("email"), datos.get("estado", "activo")),
            )
            ids_clientes[clave] = cur.fetchone()["id"]
            resultado["clientes_creados"] += 1

        for clave, datos in plan["propietarios_nuevos"].items():
            cur.execute(
                """
                INSERT INTO propietarios (nombre, apellido, dni_cuit, telefono, email, cbu_alias, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (datos["nombre"], datos["apellido"], datos.get("dni_cuit"),
                 datos.get("telefono"), datos.get("email"), datos.get("cbu_alias"), datos.get("estado", "activo")),
            )
            ids_propietarios[clave] = cur.fetchone()["id"]
            resultado["propietarios_creados"] += 1

        for unidad in plan["unidades"]:
            cliente_id = id_de(unidad.get("cliente_clave"), ids_clientes)
            propietario_id = id_de(unidad.get("propietario_clave"), ids_propietarios)

            cur.execute(
                """
                INSERT INTO unidades (tipo, direccion, identificador_interno, propietario_id, estado, tiene_gas, gas_cuenta)
                VALUES (%s, %s, %s, %s, 'vacia', %s, %s)
                ON CONFLICT (identificador_interno) DO NOTHING
                RETURNING id;
                """,
                (unidad["tipo"], unidad["direccion"], unidad["identificador_interno"],
                 propietario_id, unidad.get("tiene_gas", False), unidad.get("gas_cuenta")),
            )
            fila_nueva = cur.fetchone()
            if fila_nueva:
                unidad_id = fila_nueva["id"]
                resultado["unidades_creadas"] += 1
            else:
                cur.execute(
                    "SELECT id, gas_cuenta FROM unidades WHERE identificador_interno = %s;",
                    (unidad["identificador_interno"],),
                )
                existente = cur.fetchone()
                unidad_id = existente["id"]
                if unidad.get("gas_cuenta") and not existente["gas_cuenta"]:
                    cur.execute(
                        "UPDATE unidades SET gas_cuenta = %s, tiene_gas = TRUE WHERE id = %s;",
                        (unidad["gas_cuenta"], unidad_id),
                    )

            datos_contrato = unidad.get("contrato")
            contrato_id = None
            if datos_contrato:
                cur.execute(
                    "SELECT id, fecha_fin FROM contratos WHERE unidad_id = %s ORDER BY id DESC LIMIT 1;",
                    (unidad_id,),
                )
                existente = cur.fetchone()
                if existente:
                    contrato_id = existente["id"]
                    fecha_fin_nueva = date.fromisoformat(datos_contrato["fecha_fin"])
                    if existente["fecha_fin"] and fecha_fin_nueva > existente["fecha_fin"]:
                        cur.execute("UPDATE contratos SET fecha_fin = %s WHERE id = %s;",
                                    (fecha_fin_nueva, contrato_id))
                elif cliente_id is not None:
                    cur.execute(
                        """
                        INSERT INTO contratos
                            (cliente_id, unidad_id, fecha_inicio, fecha_fin, monto_alquiler, dia_vencimiento, deposito, estado)
                        VALUES (%s, %s, %s, %s, %s, %s, 0, 'activo')
                        RETURNING id;
                        """,
                        (cliente_id, unidad_id, datos_contrato["fecha_inicio"], datos_contrato["fecha_fin"],
                         datos_contrato["monto_alquiler"], datos_contrato["dia_vencimiento"]),
                    )
                    contrato_id = cur.fetchone()["id"]
                    cur.execute("UPDATE unidades SET estado = 'ocupada' WHERE id = %s;", (unidad_id,))
                    resultado["contratos_creados"] += 1

                if contrato_id is not None:
                    for cuota in datos_contrato["cuotas"]:
                        cur.execute(
                            """
                            INSERT INTO cuotas (contrato_id, mes, monto, estado, comprobante)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (contrato_id, mes) DO NOTHING;
                            """,
                            (contrato_id, cuota["mes"], 0, cuota["estado"], cuota.get("comprobante")),
                        )
                        resultado["cuotas_creadas"] += cur.rowcount

            for factura in unidad.get("facturas_gas", []):
                cur.execute(
                    """
                    INSERT INTO facturas_gas (unidad_id, periodo, monto, estado)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (unidad_id, periodo) DO NOTHING;
                    """,
                    (unidad_id, factura["periodo"], factura.get("monto", 0), factura["estado"]),
                )
                resultado["facturas_gas_creadas"] += cur.rowcount

        for item in plan.get("telefonos_a_actualizar", []):
            cur.execute(
                "UPDATE clientes SET telefono = %s WHERE id = %s AND (telefono IS NULL OR telefono = '');",
                (item["telefono"], item["cliente_id"]),
            )
            resultado["telefonos_actualizados"] += cur.rowcount

    conn.commit()
    return resultado
