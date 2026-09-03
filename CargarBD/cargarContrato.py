from datetime import datetime

import psycopg2
from psycopg2 import errors


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


def pedir_fecha(mensaje):
    while True:
        valor = input(mensaje + " (formato YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(valor, "%Y-%m-%d")
            return valor
        except ValueError:
            print("   Formato inválido. Usá YYYY-MM-DD, ej: 2026-03-01")


def pedir_dia_vencimiento():
    while True:
        dia = pedir_entero("Día de vencimiento del alquiler (1-31): ")
        if 1 <= dia <= 31:
            return dia
        print("   Tiene que ser un día entre 1 y 31.")


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


def cargar_contrato(conn):
    print("--- Cargar nuevo contrato ---")
    cliente_id = pedir_id_existente(conn, "clientes", "ID del cliente: ")
    unidad_id = pedir_id_existente(conn, "unidades", "ID de la unidad: ")
    fecha_inicio = pedir_fecha("Fecha de inicio")
    fecha_fin = pedir_fecha("Fecha de fin")
    monto_alquiler = pedir_decimal("Monto del alquiler: ")
    dia_vencimiento = pedir_dia_vencimiento()
    deposito = pedir_decimal("Depósito (0 si no aplica): ")

    query = """
        INSERT INTO contratos
            (cliente_id, unidad_id, fecha_inicio, fecha_fin,
             monto_alquiler, dia_vencimiento, deposito)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """

    with conn.cursor() as cur:
        try:
            cur.execute(query, (
                cliente_id, unidad_id, fecha_inicio, fecha_fin,
                monto_alquiler, dia_vencimiento, deposito,
            ))
            nuevo_id = cur.fetchone()[0]

            cur.execute("UPDATE unidades SET estado = 'ocupada' WHERE id = %s;", (unidad_id,))

            conn.commit()
            print(f"\n✅ Contrato cargado con éxito. ID asignado: {nuevo_id}")
            print("   La unidad quedó marcada como 'ocupada'.\n")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error al cargar el contrato: {e}\n")