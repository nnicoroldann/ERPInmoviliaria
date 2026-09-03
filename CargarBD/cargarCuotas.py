import re

import psycopg2
from psycopg2 import errors

ESTADOS_VALIDOS = ["pendiente", "pagado", "vencido", "parcial"]


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
            print("   Ingresá un número válido (ej: 150000 o 150000.50).")


def pedir_mes():
    while True:
        valor = input("Mes de la cuota (formato YYYY-MM, ej: 2026-03): ").strip()
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


def existe_id(conn, tabla, id_valor):
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {tabla} WHERE id = %s;", (id_valor,))
        return cur.fetchone() is not None


def pedir_id_existente(conn, tabla, mensaje):
    while True:
        id_valor = pedir_entero(mensaje)
        if existe_id(conn, tabla, id_valor):
            return id_valor
        print(f"   No existe ningún registro con id {id_valor} en '{tabla}'. Probá de nuevo.")


def cargar_cuota(conn):
    print("--- Cargar nueva cuota ---")
    contrato_id = pedir_id_existente(conn, "contratos", "ID del contrato: ")
    mes = pedir_mes()
    monto = pedir_decimal("Monto de la cuota: ")
    estado = pedir_estado()

    fecha_pago = None
    comprobante = None
    if estado in ("pagado", "parcial"):
        fecha_pago = pedir_dato("Fecha de pago (YYYY-MM-DD): ")
        comprobante = pedir_dato("Comprobante (opcional): ", obligatorio=False)

    query = """
        INSERT INTO cuotas (contrato_id, mes, monto, estado, fecha_pago, comprobante)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """

    with conn.cursor() as cur:
        try:
            cur.execute(query, (contrato_id, mes, monto, estado, fecha_pago, comprobante))
            nuevo_id = cur.fetchone()[0]
            conn.commit()
            print(f"\n✅ Cuota cargada con éxito. ID asignado: {nuevo_id}\n")
        except errors.UniqueViolation:
            conn.rollback()
            print("\n❌ Ya existe una cuota cargada para ese contrato en ese mes. No se cargó.\n")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error al cargar la cuota: {e}\n")