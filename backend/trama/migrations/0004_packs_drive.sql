-- 0004: copia de cada pack ZIP en Google Drive (E3b). El ZIP sube tal cual, verificado por md5,
-- para poder prescindir de la copia local y extraer entradas por rangos desde Drive.
ALTER TABLE packs ADD COLUMN drive_file_id TEXT;
ALTER TABLE packs ADD COLUMN drive_md5 TEXT;
ALTER TABLE packs ADD COLUMN drive_verified_at TEXT;
