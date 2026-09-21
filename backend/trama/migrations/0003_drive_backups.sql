-- 0003: ubicaciones remotas (Google Drive), verificación por checksum y registro de respaldos (E3)
ALTER TABLE locations ADD COLUMN external_id TEXT;      -- id del archivo en el proveedor remoto
ALTER TABLE locations ADD COLUMN checksum TEXT;         -- md5 informado por el proveedor (verificación de subida)
ALTER TABLE locations ADD COLUMN verified_at TEXT;
CREATE INDEX idx_locations_external ON locations(external_id);

CREATE TABLE backups (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,            -- carpeta del snapshot en TRAMA_BACKUP_DIR
  created_at TEXT NOT NULL,
  db_sha256 TEXT NOT NULL,
  db_bytes INTEGER NOT NULL,
  derivatives_bytes INTEGER NOT NULL,
  derivatives_files INTEGER NOT NULL,
  assets INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'done',   -- done | failed | uploaded
  drive_file_id TEXT,
  error TEXT
);

-- Fallos de inicio de sesión (limitación de intentos persistente entre reinicios).
CREATE TABLE auth_attempts (
  ip TEXT PRIMARY KEY,
  failures INTEGER NOT NULL DEFAULT 0,
  blocked_until TEXT
);
