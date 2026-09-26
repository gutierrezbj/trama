import { useState } from "react";
import { api } from "./api";
import { useAsync, useInterval } from "./hooks";

/** Aviso «recursos sin vista previa» con el botón que las genera todas desde los ZIP (local o Drive). */
export function PreviewsBanner() {
  const status = useAsync(() => api.previewsStatus(), []);
  const [msg, setMsg] = useState<string | null>(null);
  const s = status.data;
  const working = !!s && s.packs_queued > 0;
  useInterval(() => status.reload(true), 4000, working);
  if (!s || (s.pending === 0 && !working)) return null;
  const done = s.total - s.pending;
  const nf = new Intl.NumberFormat("es-ES");
  return (
    <div className="storage previews-banner">
      <div className="row between tiny">
        <span>Vistas previas de tus packs</span>
        <span>{nf.format(done)} de {nf.format(s.total)}</span>
      </div>
      <div className="progress"><div style={{ width: `${s.total ? (done / s.total) * 100 : 0}%` }} /></div>
      {working ? (
        <div className="tiny">Generando: {s.running?.message ?? "en cola"}{s.packs_queued > 1 ? ` · ${s.packs_queued - 1} packs en cola` : ""}. Puedes seguir usando TRAMA.</div>
      ) : (
        <div className="row" style={{ flexWrap: "wrap", alignItems: "center" }}>
          <span className="tiny">{nf.format(s.pending)} recursos aún no tienen imagen. TRAMA los lee de tus ZIP (también en Drive), crea la vista previa y no guarda copia.</span>
          <button type="button" className="btn small primary" onClick={() => api.previewsAll().then((r) => { setMsg(r.unreachable ? `${r.unreachable} packs no accesibles ahora` : null); status.reload(true); }).catch((e) => setMsg((e as Error).message))}>Generar vistas previas</button>
        </div>
      )}
      {msg && <div className="tiny">{msg}</div>}
    </div>
  );
}
