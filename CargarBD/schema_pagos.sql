-- schema_pagos.sql
--
-- Tabla para llevar registro de cada intento de pago con Mercado Pago,
-- ya sea de una cuota de alquiler, una factura de gas o una de agua.
-- Sirve tanto para saber qué se cobró (trazabilidad para el admin) como
-- para que el webhook sepa qué marcar como pagado cuando Mercado Pago
-- confirma un cobro.
--
-- "tipo" + "referencia_id" apuntan a la fila real: ('cuota', 123) es
-- cuotas.id = 123, ('gas', 45) es facturas_gas.id = 45, etc.
--
-- "grupo_pago" es un identificador que generamos nosotros ANTES de
-- pedirle la preferencia a Mercado Pago, y se lo mandamos como
-- "external_reference". Cuando el inquilino usa "Pagar todo lo
-- pendiente" se crea UNA sola preferencia con varios ítems, y todas
-- las filas de ese pago comparten el mismo grupo_pago: así el webhook
-- sabe, con un solo external_reference, qué filas marcar como pagadas.

CREATE TABLE IF NOT EXISTS pagos_mercadopago (
    id SERIAL PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('cuota', 'gas', 'agua')),
    referencia_id INT NOT NULL,
    contrato_id INT NOT NULL REFERENCES contratos(id),
    grupo_pago VARCHAR(64) NOT NULL,
    mp_preference_id VARCHAR(120),
    mp_payment_id VARCHAR(120),
    monto NUMERIC(12,2) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'aprobado', 'rechazado')),
    creado_en TIMESTAMP NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pagos_mp_grupo ON pagos_mercadopago (grupo_pago);
CREATE INDEX IF NOT EXISTS idx_pagos_mp_tipo_ref ON pagos_mercadopago (tipo, referencia_id);
CREATE INDEX IF NOT EXISTS idx_pagos_mp_contrato ON pagos_mercadopago (contrato_id);
