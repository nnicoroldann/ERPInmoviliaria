import re

import psycopg2
from psycopg2 import errors

ESTADOS_VALIDOS = ["pendiente", "pagado", "vencido"]


def pedir_dato(mensaje, obligatorio=True):
    while True:
        valor = input(mensaje).strip()
        if valor or not obligatorio:
            return valor or None
        print("   Este dato es obligatorio, no puede quedar vacío.")


def pedir_entero(mensaje):
    while True:
        valor = input(mensaje).strip()
        if valor.isdigit():
            return int(valor)
        print("   Ingresá un número entero válido.")


def pedir_decimal(mensaje):
    while True:
        valor = input(mensaje).strip().replace(",", ".")
        try:
            return float(valor)
        except ValueError:
            print("   Ingresá un número válido (ej: 15000 o 15000.50).")


def pedir_periodo():
    while True:
        valor = input("Período de la factura (formato YYYY-MM, ej: 2026-03): ").strip()
        if re.fullmatch(r"\d{4}-\d{2}", valor):
            return valor
        print("   Formato inválido. Usá YYYY-MM.")


def pedir_estado():
    while True:
        estado = input(f"Estado ({'/'.join(ESTADOS_VALIDOS)}) [pendiente]: ").strip().lower()
        if estado == "":
            return "pendiente"
        if estado in ESTADOS_VALIDOS:
            return estado
        print(f"   Estado inválido. Opciones válidas: {', '.join(ESTADOS_VALIDOS)}")


def obtener_unidad(conn, unidad_id):
    with conn.cursor() as cur:
        cur.execute("SELECT tiene_gas FROM unidades WHERE id = %s;", (unidad_id,))
        return cur.fetchone()


def pedir_unidad_con_gas(conn):
    while True:
        unidad_id = pedir_entero("ID de la unidad: ")
        fila = obtener_unidad(conn, unidad_id)
        if fila is None:
            print(f"   No existe ninguna unidad con id {unidad_id}. Probá de nuevo.")
            continue
        tiene_gas = fila[0]
        if not tiene_gas:
            confirmar = input(
                "   ⚠️  Esa unidad está marcada como sin gas. ¿Cargar la factura igual? (s/n): "
            ).strip().lower()
            if confirmar != "s":
                continue
        return unidad_id


def cargar_factura_gas(conn):
    print("--- Cargar nueva factura de gas ---")
    unidad_id = pedir_unidad_con_gas(conn)
    periodo = pedir_periodo()
    monto = pedir_decimal("Monto de la factura: ")
    estado = pedir_estado()
    vencimiento = pedir_dato("Fecha de vencimiento (YYYY-MM-DD, opcional): ", obligatorio=False)

    pagado_en = None
    if estado == "pagado":
        pagado_en = pedir_dato("Fecha en que se pagó (YYYY-MM-DD): ")

    query = """
        INSERT INTO facturas_gas (unidad_id, periodo, monto, estado, vencimiento, pagado_en)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """

    with conn.cursor() as cur:
        try:
            cur.execute(query, (unidad_id, periodo, monto, estado, vencimiento, pagado_en))
            nuevo_id = cur.fetchone()[0]
            conn.commit()
            print(f"\n✅ Factura de gas cargada con éxito. ID asignado: {nuevo_id}\n")
        except errors.UniqueViolation:
            conn.rollback()
            print("\n❌ Ya existe una factura cargada para esa unidad en ese período. No se cargó.\n")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error al cargar la factura: {e}\n")