-- ============================================================
-- schema_inquilinos.sql
--
-- Agrega el "portal del inquilino": un tercer rol de usuario
-- ('inquilino') vinculado a un registro de la tabla clientes, para
-- que cada inquilino pueda entrar a su propia cuenta y ver
-- únicamente su(s) contrato(s) y su estado de cuotas/gas/agua.
--
-- También agrega la tabla facturas_agua, con la misma estructura
-- que facturas_gas, para poder trackear el servicio de agua igual
-- que el de gas.
--
-- Se puede correr más de una vez sin problema.
-- ============================================================

-- 1) Permitir el rol 'inquilino' en usuarios, y vincularlo a un cliente.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_rol_check;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_rol_check
    CHECK (rol IN ('admin', 'usuario', 'inquilino'));

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clientes(id);
CREATE INDEX IF NOT EXISTS idx_usuarios_cliente_id ON usuarios (cliente_id);

-- Un usuario con rol 'inquilino' siempre tiene que estar vinculado a un cliente.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_inquilino_cliente_check;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_inquilino_cliente_check
    CHECK (rol <> 'inquilino' OR cliente_id IS NOT NULL);

-- 2) Facturas de agua (mismo esquema que facturas_gas).
CREATE TABLE IF NOT EXISTS facturas_agua (
    id SERIAL PRIMARY KEY,
    unidad_id INT NOT NULL REFERENCES unidades(id),
    periodo CHAR(7) NOT NULL,                -- 'YYYY-MM'
    monto NUMERIC(12,2) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    vencimiento DATE,
    pagado_en DATE,
    UNIQUE (unidad_id, periodo)
);
