"""
aplicar_sql.py

Runner genérico para aplicar cualquier archivo .sql de esta carpeta
contra la base de datos, usando las credenciales de Web/.env
(las mismas que usa la app). Sirve para no depender de tener
"psql" instalado.

Uso (desde la raíz del proyecto, con el venv activado):

    python CargarBD/aplicar_sql.py schema_propietarios.sql
    python CargarBD/aplicar_sql.py schema_usuarios.sql
"""

import os
import sys
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


def main():
    if len(sys.argv) != 2:
        print("Uso: python CargarBD/aplicar_sql.py <archivo.sql>")
        print("Ejemplo: python CargarBD/aplicar_sql.py schema_propietarios.sql")
        raise SystemExit(1)

    nombre_archivo = sys.argv[1]
    sql_path = Path(__file__).resolve().parent / nombre_archivo
    if not sql_path.exists():
        print(f"No encontré el archivo: {sql_path}")
        raise SystemExit(1)

    print(f"Conectando a la base '{DB_CONFIG['dbname']}' como '{DB_CONFIG['user']}'...")
    conn = psycopg2.connect(**DB_CONFIG)

    print(f"Aplicando {sql_path.name}...")
    sql = sql_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    conn.close()
    print("Listo, todo OK.")


if __name__ == "__main__":
    main()
