-- 0002: packs (ZIP), entradas de pack, identidad provisional, duplicados y preview del proveedor (E2)
CREATE TABLE packs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  rel_path TEXT NOT NULL,              -- ruta del ZIP relativa a la raíz permitida
  label TEXT NOT NULL,                 -- procedencia/compra, editable
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | indexing | indexed | failed | offline
  entries_total INTEGER NOT NULL DEFAULT 0,
  entries_media INTEGER NOT NULL DEFAULT 0,
  entries_unsafe INTEGER NOT NULL DEFAULT 0,
  bytes_total INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  indexed_at TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(source_id, rel_path)
);

CREATE TABLE pack_entries (
  id TEXT PRIMARY KEY,
  pack_id TEXT NOT NULL REFERENCES packs(id) ON DELETE CASCADE,
  inner_path TEXT NOT NULL,            -- ruta interna normalizada con '/'
  file_name TEXT NOT NULL,
  ext TEXT NOT NULL,
  media_kind TEXT NOT NULL,            -- video | audio | image | other | ignored
  size INTEGER NOT NULL,               -- tamaño declarado sin comprimir
  compressed_size INTEGER NOT NULL,
  crc32 INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'archived',  -- archived | extracted | failed | unsafe | ignored
  unsafe_reason TEXT,
  error TEXT,
  version_id TEXT REFERENCES asset_versions(id),
  extracted_at TEXT,
  UNIQUE(pack_id, inner_path)
);
CREATE INDEX idx_pack_entries_pack ON pack_entries(pack_id, status);
CREATE INDEX idx_pack_entries_version ON pack_entries(version_id);

-- Identidad provisional (crc32+tamaño) hasta disponer de los bytes y el SHA-256 completo.
ALTER TABLE asset_versions ADD COLUMN identity_kind TEXT NOT NULL DEFAULT 'sha256';   -- sha256 | provisional

-- Ubicaciones dentro de un pack: kind='pack', rel_path = '<zip>!/<ruta interna>'; status archived cuando no está extraída.
ALTER TABLE locations ADD COLUMN kind TEXT NOT NULL DEFAULT 'local';                  -- local | pack
ALTER TABLE locations ADD COLUMN pack_entry_id TEXT REFERENCES pack_entries(id);
CREATE INDEX idx_locations_pack_entry ON locations(pack_entry_id);

-- Duplicado confirmado por hash que conserva su ficha por tener ediciones humanas o pertenencias.
ALTER TABLE assets ADD COLUMN duplicate_of TEXT REFERENCES assets(id);
-- Preview suministrada por el proveedor (archivo hermano con el mismo nombre base).
ALTER TABLE assets ADD COLUMN provider_preview_asset_id TEXT REFERENCES assets(id);
