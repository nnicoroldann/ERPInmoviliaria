-- ============================================================
-- schema_propietarios.sql
--
-- Agrega el concepto de "propietario" (dueño de una unidad),
-- que hoy no existe en la base aunque sí aparece en el Excel de
-- la inmobiliaria (columna DUEÑO/PROPIETARIO en varias hojas).
--
-- Crea la tabla "propietarios" y agrega la columna propietario_id
-- a "unidades" para saber de quién es cada propiedad.
--
-- Se puede correr más de una vez sin problema (usa IF NOT EXISTS).
-- ============================================================

CREATE TABLE IF NOT EXISTS propietarios (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(150) NOT NULL,
    apellido    VARCHAR(150) NOT NULL,
    dni_cuit    VARCHAR(20) UNIQUE,
    telefono    VARCHAR(30),
    email       VARCHAR(150) UNIQUE,
    cbu_alias   VARCHAR(60),              -- para liquidarle el alquiler
    estado      VARCHAR(20) NOT NULL DEFAULT 'activo'  -- activo / inactivo
);

CREATE INDEX IF NOT EXISTS idx_propietarios_dni_cuit ON propietarios (dni_cuit);

ALTER TABLE unidades ADD COLUMN IF NOT EXISTS propietario_id INTEGER REFERENCES propietarios(id);
CREATE INDEX IF NOT EXISTS idx_unidades_propietario_id ON unidades (propietario_id);
