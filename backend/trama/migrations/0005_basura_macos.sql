-- Archivos basura de macOS dentro de los ZIP (AppleDouble «._nombre» y carpetas __MACOSX) que se
-- catalogaron como recursos. No son multimedia: se marcan como ignorados y sus fichas se retiran.
-- No se toca ningún ZIP ni original.
CREATE TEMP TABLE basura AS
  SELECT id, version_id FROM pack_entries
  WHERE substr(file_name, 1, 2) = '._' OR instr(inner_path, '__MACOSX/') > 0;

DELETE FROM locations WHERE pack_entry_id IN (SELECT id FROM basura);

UPDATE pack_entries SET status = 'ignored', media_kind = 'ignored', version_id = NULL, error = NULL
  WHERE id IN (SELECT id FROM basura);

-- Versiones que ya no tienen ninguna ubicación ni entrada: se retiran con sus fichas.
CREATE TEMP TABLE versiones_huerfanas AS
  SELECT DISTINCT version_id AS id FROM basura
  WHERE version_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM locations l WHERE l.version_id = basura.version_id)
    AND NOT EXISTS (SELECT 1 FROM pack_entries pe WHERE pe.version_id = basura.version_id);

CREATE TEMP TABLE fichas_huerfanas AS
  SELECT id FROM assets WHERE version_id IN (SELECT id FROM versiones_huerfanas);

UPDATE assets SET duplicate_of = NULL WHERE duplicate_of IN (SELECT id FROM fichas_huerfanas);
UPDATE assets SET provider_preview_asset_id = NULL WHERE provider_preview_asset_id IN (SELECT id FROM fichas_huerfanas);
DELETE FROM selection_items WHERE asset_id IN (SELECT id FROM fichas_huerfanas);
DELETE FROM collection_assets WHERE asset_id IN (SELECT id FROM fichas_huerfanas);
DELETE FROM assets WHERE id IN (SELECT id FROM fichas_huerfanas);
DELETE FROM derivatives WHERE version_id IN (SELECT id FROM versiones_huerfanas);
DELETE FROM jobs WHERE version_id IN (SELECT id FROM versiones_huerfanas);
DELETE FROM asset_versions WHERE id IN (SELECT id FROM versiones_huerfanas);

UPDATE packs SET entries_media = (
  SELECT COUNT(*) FROM pack_entries pe WHERE pe.pack_id = packs.id AND pe.status IN ('archived', 'extracted', 'failed')
);

DROP TABLE basura;
DROP TABLE versiones_huerfanas;
DROP TABLE fichas_huerfanas;
