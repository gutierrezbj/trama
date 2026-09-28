-- Etiquetas de nivel 1: se deducen de las carpetas y de los datos medidos, sin IA y sin coste.
-- Van aparte de las etiquetas humanas para poder recalcularlas sin pisar nada.
ALTER TABLE assets ADD COLUMN auto_tags TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
