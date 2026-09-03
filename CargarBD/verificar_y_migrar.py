"""
verificar_y_migrar.py

Script de uso único para:
1. Mostrar las columnas reales de la tabla "clientes" (para chequear
   si se llama "dni" o "dni_cuit").
2. Aplicar schema_usuarios.sql (crear la tabla "usuarios") si todavía
   no existe.

Se conecta usando las credenciales de Web/.env (las mismas que ya usa
la app). Correr desde la raíz del proyecto o desde donde sea, con:

    python CargarBD/verificar_y_migrar.py
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "Web" / ".env")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

print(f"Conectando a la base '{DB_CONFIG['dbname']}' como '{DB_CONFIG['user']}'...")
conn = psycopg2.connect(**DB_CONFIG)

print("\n=== Columnas actuales de la tabla 'clientes' ===")
with conn.cursor() as cur:
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'clientes'
        ORDER BY ordinal_position;
        """
    )
    for nombre, tipo in cur.fetchall():
        print(f"  - {nombre} ({tipo})")

print("\n=== Aplicando CargarBD/schema_usuarios.sql ===")
sql_path = BASE_DIR / "CargarBD" / "schema_usuarios.sql"
sql = sql_path.read_text(encoding="utf-8")
with conn.cursor() as cur:
    cur.execute(sql)
conn.commit()
print("Listo: la tabla 'usuarios' quedó creada (o ya existía).")

conn.close()
print("\nConexión cerrada. Todo OK.")
