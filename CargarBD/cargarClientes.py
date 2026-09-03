"""
cargar_cliente.py

Script simple que se conecta a la base de datos PostgreSQL del
mini-ERP de alquileres y carga un nuevo cliente preguntando los
datos por consola.

Requisitos:
    pip install psycopg2-binary

Antes de correrlo, completá los datos de conexión más abajo
(DB_CONFIG) con los de tu base.
"""

import os
import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------
# 1. DATOS DE CONEXIÓN — se leen desde el archivo .env
# -----------------------------------------------------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}


def conectar():
    """Abre la conexión a la base y devuelve el objeto connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Conectado a la base de datos.\n")
        return conn
    except psycopg2.OperationalError as e:
        print("❌ No se pudo conectar a la base de datos.")
        print(f"   Detalle: {e}")
        raise SystemExit(1)


def pedir_dato(mensaje, obligatorio=True):
    """Pide un dato por consola. Si es obligatorio, no deja seguir vacío."""
    while True:
        valor = input(mensaje).strip()
        if valor or not obligatorio:
            return valor or None  # si está vacío y no es obligatorio, guarda NULL
        print("   Este dato es obligatorio, no puede quedar vacío.")


def cargar_cliente(conn):
    """Pregunta los datos del cliente y los inserta en la tabla clientes."""
    print("--- Cargar nuevo cliente ---")
    nombre = pedir_dato("Nombre: ")
    apellido = pedir_dato("Apellido: ")
    dni_cuit = pedir_dato("DNI/CUIT: ")
    telefono = pedir_dato("Teléfono (opcional): ", obligatorio=False)
    email = pedir_dato("Email (opcional): ", obligatorio=False)

    query = """
        INSERT INTO clientes (nombre, apellido, dni_cuit, telefono, email)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id;
    """

    with conn.cursor() as cur:
        try:
            cur.execute(query, (nombre, apellido, dni_cuit, telefono, email))
            nuevo_id = cur.fetchone()[0]
            conn.commit()
            print(f"\n✅ Cliente cargado con éxito. ID asignado: {nuevo_id}\n")
        except errors.UniqueViolation:
            conn.rollback()
            print("\n❌ Ya existe un cliente con ese DNI/CUIT o email. No se cargó.\n")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error al cargar el cliente: {e}\n")


def main():
    conn = conectar()
    try:
        while True:
            cargar_cliente(conn)
            otro = input("¿Cargar otro cliente? (s/n): ").strip().lower()
            if otro != "s":
                break
    finally:
        conn.close()
        print("Conexión cerrada. Chau!")


if __name__ == "__main__":
    main()