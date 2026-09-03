-- ============================================================
-- schema_usuarios.sql
--
-- Crea la tabla "usuarios" que usa el sistema de login del ERP
-- (modo administrador / modo usuario). Ejecutar UNA sola vez
-- contra la base de datos ya existente.
--
-- Cómo correrlo:
--   psql -h localhost -U Support -d bd_ERPInmobiliaria -f CargarBD/schema_usuarios.sql
--
-- (los valores de host/usuario/base son los que ya tenés en tu .env)
-- ============================================================

CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    nombre_usuario  VARCHAR(50)  NOT NULL UNIQUE,
    email           VARCHAR(120) NOT NULL UNIQUE,
    password_hash   VARCHAR(200) NOT NULL,
    rol             VARCHAR(20)  NOT NULL DEFAULT 'usuario'
                        CHECK (rol IN ('admin', 'usuario')),
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios (email);
CREATE INDEX IF NOT EXISTS idx_usuarios_nombre_usuario ON usuarios (nombre_usuario);

-- Nota: no se crea ningún usuario acá. El primer usuario que se
-- registre desde /registro en la web queda como "admin"
-- automáticamente; el resto queda como "usuario" por defecto.
