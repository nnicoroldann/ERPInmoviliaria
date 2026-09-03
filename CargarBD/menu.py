"""
menu.py

Menu principal del mini-ERP de alquileres. Reune los modulos de
carga de clientes, unidades, contratos, cuotas y facturas de gas
en un solo programa con menu de opciones.

IMPORTANTE: este archivo tiene que estar en la MISMA carpeta que:
    cargarClientes.py
    cargarUnidad.py
    cargarContrato.py
    cargarCuotas.py
    cargarFacturas.py

Requisitos:
    pip3 install psycopg2-binary
"""

import psycopg2

import cargarClientes
import cargarUnidad
import cargarContrato
import cargarCuotas
import cargarFacturas

import os
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------
# DATOS DE CONEXION - se leen desde el archivo .env
# -----------------------------------------------------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}


def conectar():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("Conectado a la base de datos.\n")
        return conn
    except psycopg2.OperationalError as e:
        print("No se pudo conectar a la base de datos.")
        print(f"   Detalle: {e}")
        raise SystemExit(1)


def mostrar_menu():
    print("=" * 40)
    print("   MINI-ERP DE ALQUILERES - MENU")
    print("=" * 40)
    print("1) Cargar cliente")
    print("2) Cargar unidad")
    print("3) Cargar contrato")
    print("4) Cargar cuota")
    print("5) Cargar factura de gas")
    print("0) Salir")
    print("=" * 40)


def main():
    conn = conectar()

    opciones = {
        "1": cargarClientes.cargar_cliente,
        "2": cargarUnidad.cargar_unidad,
        "3": cargarContrato.cargar_contrato,
        "4": cargarCuotas.cargar_cuota,
        "5": cargarFacturas.cargar_factura_gas,
    }

    try:
        while True:
            mostrar_menu()
            opcion = input("Elegi una opcion: ").strip()

            if opcion == "0":
                print("\nSaliendo del sistema...")
                break

            funcion = opciones.get(opcion)
            if funcion is None:
                print("\nOpcion invalida, proba de nuevo.\n")
                continue

            funcion(conn)
            input("Presiona Enter para volver al menu...")
            print()

    finally:
        conn.close()
        print("Conexion cerrada. Chau!")


if __name__ == "__main__":
    main()