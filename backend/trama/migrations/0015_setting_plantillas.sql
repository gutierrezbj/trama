-- Las plantillas de DaVinci (.setting de Fusion, .preset, .drfx, .drp) viven todas en
-- «Plantillas»; las .setting se habían repartido por carpeta. Lo fijado a mano no se toca.
UPDATE assets SET category = 'plantillas'
WHERE category_source = 'inferred'
  AND version_id IN (SELECT id FROM asset_versions WHERE ext IN ('.setting', '.preset', '.drfx', '.drp'));
