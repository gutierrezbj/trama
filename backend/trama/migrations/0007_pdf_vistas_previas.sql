-- Los PDF pasan a tener vista previa (primera página) y enlaces a su vídeo: los que ya se
-- analizaron sin soporte vuelven a pendiente para que la cola de vistas previas los procese.
UPDATE asset_versions SET analysis_status = 'pending'
  WHERE ext = '.pdf' AND analysis_status = 'done'
    AND (analysis IS NULL OR json_extract(analysis, '$.preview_support') IS NULL OR json_extract(analysis, '$.preview_support') = 'none');
