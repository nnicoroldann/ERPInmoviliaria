-- ============================================================
-- schema_ajustes.sql
--
-- Agrega el ajuste de alquiler por índice (ICL / IPC / RIPTE) a los
-- contratos, y una tabla para ir guardando los valores de esos
-- índices que se van trayendo de las fuentes públicas (para no tener
-- que pedirlos de nuevo cada vez, y para poder auditar con qué valor
-- se calculó cada ajuste).
--
-- monto_base / valor_indice_base son el "ancla" del último ajuste:
-- el próximo ajuste se calcula como
--     monto_base * (valor_del_índice_hoy / valor_indice_base)
-- y al confirmarlo, monto_base y valor_indice_base se actualizan al
-- nuevo valor, quedando esa fecha como el nuevo punto de partida.
--
-- Se puede correr más de una vez sin problema (usa IF NOT EXISTS).
-- ============================================================

ALTER TABLE contratos ADD COLUMN IF NOT EXISTS indice_ajuste VARCHAR(20) NOT NULL DEFAULT 'ninguno';
ALTER TABLE contratos ADD COLUMN IF NOT EXISTS periodicidad_ajuste VARCHAR(20) NOT NULL DEFAULT 'anual';
ALTER TABLE contratos ADD COLUMN IF NOT EXISTS fecha_ultimo_ajuste DATE;
ALTER TABLE contratos ADD COLUMN IF NOT EXISTS monto_base NUMERIC(12,2);
ALTER TABLE contratos ADD COLUMN IF NOT EXISTS valor_indice_base NUMERIC(14,4);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'contratos_indice_ajuste_check'
    ) THEN
        ALTER TABLE contratos ADD CONSTRAINT contratos_indice_ajuste_check
            CHECK (indice_ajuste IN ('ninguno', 'icl', 'ipc', 'ripte'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'contratos_periodicidad_ajuste_check'
    ) THEN
        ALTER TABLE contratos ADD CONSTRAINT contratos_periodicidad_ajuste_check
            CHECK (periodicidad_ajuste IN ('trimestral', 'semestral', 'anual'));
    END IF;
END $$;

-- A los contratos que ya existían les faltaría el punto de partida
-- del ajuste: lo completamos con lo que ya tenían (su alquiler actual
-- y su fecha de inicio), así el primer cálculo de ajuste sale bien.
UPDATE contratos SET monto_base = monto_alquiler WHERE monto_base IS NULL;
UPDATE contratos SET fecha_ultimo_ajuste = fecha_inicio WHERE fecha_ultimo_ajuste IS NULL;

CREATE TABLE IF NOT EXISTS valores_indice (
    id          SERIAL PRIMARY KEY,
    indice      VARCHAR(20) NOT NULL CHECK (indice IN ('icl', 'ipc', 'ripte')),
    fecha       DATE NOT NULL,
    valor       NUMERIC(14,4) NOT NULL,
    fuente      VARCHAR(200),
    creado_en   TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (indice, fecha)
);
