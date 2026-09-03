-- schema_boletas.sql
--
-- Permite que el inquilino suba el comprobante (foto o PDF) de su
-- boleta de gas o agua desde su portal, en vez de que el admin la
-- cargue siempre a mano.
--
-- comprobante_path: nombre del archivo guardado en Web/uploads_privados/comprobantes/
--   (NULL si esa factura se cargó del modo tradicional, sin comprobante adjunto).
-- subido_por: quién generó la fila. 'inquilino' cuando el propio inquilino
--   la subió desde su portal (con datos leídos automáticamente y confirmados
--   por él); 'admin' es el valor por defecto para todo lo cargado como hasta ahora.

ALTER TABLE facturas_gas ADD COLUMN IF NOT EXISTS comprobante_path VARCHAR(255);
ALTER TABLE facturas_gas ADD COLUMN IF NOT EXISTS subido_por VARCHAR(20) NOT NULL DEFAULT 'admin';
ALTER TABLE facturas_gas DROP CONSTRAINT IF EXISTS facturas_gas_subido_por_check;
ALTER TABLE facturas_gas ADD CONSTRAINT facturas_gas_subido_por_check
    CHECK (subido_por IN ('admin', 'inquilino'));

ALTER TABLE facturas_agua ADD COLUMN IF NOT EXISTS comprobante_path VARCHAR(255);
ALTER TABLE facturas_agua ADD COLUMN IF NOT EXISTS subido_por VARCHAR(20) NOT NULL DEFAULT 'admin';
ALTER TABLE facturas_agua DROP CONSTRAINT IF EXISTS facturas_agua_subido_por_check;
ALTER TABLE facturas_agua ADD CONSTRAINT facturas_agua_subido_por_check
    CHECK (subido_por IN ('admin', 'inquilino'));
