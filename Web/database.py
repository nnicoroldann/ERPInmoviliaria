"""
database.py

Maneja la conexion a la base de datos PostgreSQL del mini-ERP.
Todos los routers importan get_connection() desde aca.
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}


def get_connection():
    """Devuelve una conexion cuyas filas se comportan como diccionarios."""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)
