import psycopg2
from psycopg2 import errors

TIPOS_VALIDOS = ["casa", "local", "cochera"]


def pedir_dato(mensaje, obligatorio=True):
    while True:
        valor = input(mensaje).strip()
        if valor or not obligatorio:
            return valor or None
        print("   Este dato es obligatorio, no puede quedar vacío.")


def pedir_tipo():
    while True:
        tipo = input(f"Tipo ({'/'.join(TIPOS_VALIDOS)}): ").strip().lower()
        if tipo in TIPOS_VALIDOS:
            return tipo
        print(f"   Tipo inválido. Opciones válidas: {', '.join(TIPOS_VALIDOS)}")


def pedir_bool(mensaje):
    while True:
        valor = input(mensaje).strip().lower()
        if valor in ("s", "si", "sí"):
            return True
        if valor in ("n", "no"):
            return False
        print("   Respondé 's' o 'n'.")


def cargar_unidad(conn):
    print("--- Cargar nueva unidad ---")
    tipo = pedir_tipo()
    direccion = pedir_dato("Dirección: ")
    identificador_interno = pedir_dato("Identificador interno (opcional): ", obligatorio=False)
    tiene_gas = pedir_bool("¿Tiene gas? (s/n): ")

    query = """
        INSERT INTO unidades (tipo, direccion, identificador_interno, tiene_gas)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
    """

    with conn.cursor() as cur:
        try:
            cur.execute(query, (tipo, direccion, identificador_interno, tiene_gas))
            nuevo_id = cur.fetchone()[0]
            conn.commit()
            print(f"\n✅ Unidad cargada con éxito. ID asignado: {nuevo_id}\n")
        except errors.UniqueViolation:
            conn.rollback()
            print("\n❌ Ya existe una unidad con ese identificador interno. No se cargó.\n")
        except Exception as e:
            conn.rollback()
            print(f"\n❌ Error al cargar la unidad: {e}\n")