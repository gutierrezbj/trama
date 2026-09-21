import { useState } from "react";
import { api, type Asset, CATEGORY_LABELS, formatDuration, originalUrl } from "./api";
import { useAsync } from "./hooks";
import { IconDown, IconDownload, IconSelection, IconUp } from "./icons";

interface ListProps {
  onOpen: (id: string) => void;
  refreshKey: number;
}

export function SelectionsList({ onOpen, refreshKey }: ListProps) {
  const list = useAsync(() => api.selections(), [refreshKey]);
  const [name, setName] = useState("");
  return (
    <>
      <div className="view-head"><h1>Mis selecciones</h1><p>Reúne recursos para una producción sin duplicar bytes.</p></div>
      <form className="create-row" onSubmit={async (e) => { e.preventDefault(); if (!name.trim()) return; const s = await api.createSelection(name.trim()); setName(""); list.reload(); onOpen(s.id); }}>
        <input className="input" placeholder="Nueva selección…" aria-label="Nombre de la nueva selección" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn primary" disabled={!name.trim()}>Crear</button>
      </form>
      {list.error && <div className="notice warn">{list.error}</div>}
      {list.data && list.data.length === 0 && <div className="empty"><h2>Sin selecciones</h2><p>Crea una aquí o desde «Añadir a selección» en la ficha de un recurso.</p></div>}
      <div className="cards">
        {(list.data ?? []).map((s) => (
          <button type="button" key={s.id} className="list-card" onClick={() => onOpen(s.id)}>
            <div className="cover">{s.cover_asset_id ? <img src={`/api/assets/${s.cover_asset_id}/thumb`} alt="" /> : <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)" }}><IconSelection /></div>}</div>
            <h3>{s.name}</h3>
            <span className="tiny">{s.count ?? 0} {s.count === 1 ? "recurso" : "recursos"}{s.notes ? ` · ${s.notes}` : ""}</span>
          </button>
        ))}
      </div>
    </>
  );
}

interface DetailProps {
  id: string;
  selectedId: string | null;
  onOpenAsset: (a: Asset, el: HTMLElement) => void;
  onBack: () => void;
  onChanged: () => void;
  refreshKey: number;
}

export function SelectionDetail(props: DetailProps) {
  const sel = useAsync(() => api.selection(props.id), [props.id, props.refreshKey]);
  const [name, setName] = useState<string | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const s = sel.data;
  const move = async (index: number, dir: -1 | 1) => {
    if (!s) return;
    const ids = s.items.map((i) => i.id);
    const j = index + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    await api.orderSelection(s.id, ids);
    sel.reload(true);
  };
  if (sel.error) return <div className="notice warn">{sel.error}</div>;
  return (
    <>
      <div className="detail-head">
        <button type="button" className="btn ghost small" onClick={props.onBack}>← Selecciones</button>
        <h1>
          <input aria-label="Nombre de la selección" value={name ?? s?.name ?? ""} onChange={(e) => setName(e.target.value)}
            onBlur={async () => { if (name !== null && s && name.trim() && name !== s.name) { await api.patchSelection(s.id, { name: name.trim() }); props.onChanged(); sel.reload(true); } setName(null); }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        </h1>
        <span className="muted">{s?.items.length ?? 0} {s?.items.length === 1 ? "recurso" : "recursos"}</span>
        <button type="button" className="btn small" style={{ marginLeft: "auto" }} onClick={async () => { try { const r = await api.driveUploadSelection(props.id); setMsg(`${r.queued} subidas a Drive en cola${r.skipped_offline ? `, ${r.skipped_offline} omitidas (original no disponible aquí)` : ""}`); } catch (e) { setMsg((e as Error).message); } }}>Copiar la selección a Drive</button>
        <button type="button" className="btn ghost small danger" onClick={async () => { if (s && window.confirm(`¿Eliminar la selección «${s.name}»? Los recursos y sus originales no se borran.`)) { await api.deleteSelection(s.id); props.onChanged(); props.onBack(); } }}>Eliminar selección</button>
      </div>
      <textarea className="notes" aria-label="Notas de la selección" placeholder="Notas de producción…" value={notes ?? s?.notes ?? ""} onChange={(e) => setNotes(e.target.value)}
        onBlur={async () => { if (notes !== null && s && notes !== s.notes) { await api.patchSelection(s.id, { notes }); sel.reload(true); } setNotes(null); }} />
      {msg && <div className="notice" role="status" style={{ marginBottom: 12 }}>{msg}</div>}
      {s && s.items.length === 0 && <div className="empty"><h2>Selección vacía</h2><p>Añade recursos desde «Añadir a selección» en la ficha.</p></div>}
      <div className="sel-items">
        {(s?.items ?? []).map((a, i) => (
          <div className="sel-item" key={a.id} aria-selected={a.id === props.selectedId}>
            <button type="button" className={`thumb${a.preview.kind === "video_alpha" ? " checker" : ""}`} style={{ padding: 0, border: 0 }} aria-label={`Abrir ${a.title}`} onClick={(e) => props.onOpenAsset(a, e.currentTarget)}>
              {a.thumb_url ? <img src={a.thumb_url} alt="" /> : a.waveform_url ? <img src={a.waveform_url} alt="" style={{ objectFit: "contain" }} /> : null}
            </button>
            <div style={{ minWidth: 0 }}>
              <div className="row">
                <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title}</strong>
                <span className="tiny">{CATEGORY_LABELS[a.category] ?? a.category} · {a.version.ext.replace(".", "").toUpperCase()} · {formatDuration(a.summary.duration_s)}</span>
                {!a.available && <span className="tiny" style={{ color: "var(--danger)" }}>original offline</span>}
              </div>
              <input className="note" aria-label={`Nota para ${a.title}`} placeholder="Nota para esta pieza…" defaultValue={a.item_note ?? ""} onBlur={(e) => e.target.value !== (a.item_note ?? "") && api.patchSelectionItem(props.id, a.id, e.target.value).then(() => sel.reload(true))} />
            </div>
            <div className="ops">
              <button type="button" className="icon-btn" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}><IconUp /></button>
              <button type="button" className="icon-btn" aria-label="Bajar" disabled={i === (s?.items.length ?? 0) - 1} onClick={() => move(i, 1)}><IconDown /></button>
              <a className="icon-btn" aria-label={`Descargar original de ${a.title}`} href={originalUrl(a)} download={a.locations[0]?.file_name} aria-disabled={!a.available} onClick={(e) => !a.available && e.preventDefault()}><IconDownload /></a>
              <button type="button" className="btn ghost small" onClick={async () => { await api.removeFromSelection(props.id, a.id); props.onChanged(); sel.reload(true); }}>Quitar</button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
