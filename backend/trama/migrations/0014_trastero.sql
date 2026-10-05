-- Índice del «trastero»: fichas de paquetes de catálogos externos (comprados o suscritos) que no
-- se descargan; al buscar en TRAMA aparecen como «también lo tienes allí», con su enlace.
CREATE TABLE external_items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,            -- p. ej. «Editor Infinity»
  name TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  size_bytes INTEGER,
  page_url TEXT NOT NULL DEFAULT '',
  cover_url TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  search_text TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  UNIQUE(source, name)
);
