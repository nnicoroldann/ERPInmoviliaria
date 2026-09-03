-- schema_import_excel.sql
--
-- Columna para el número de cuenta de gas de cada unidad (lo trae la
-- hoja "GAS" del Excel de la inmobiliaria) y para saber qué se cargó
-- por el importador de Excel en vez de a mano.

ALTER TABLE unidades ADD COLUMN IF NOT EXISTS gas_cuenta VARCHAR(30);
