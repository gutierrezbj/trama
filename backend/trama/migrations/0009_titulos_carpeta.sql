-- Títulos: file (del nombre del archivo), folder (armado con las carpetas porque el nombre no
-- dice nada, p. ej. «2.mov») o human (puesto a mano; nunca se recalcula).
ALTER TABLE assets ADD COLUMN title_source TEXT NOT NULL DEFAULT 'file';
