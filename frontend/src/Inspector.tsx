import { useEffect, useRef, useState } from "react";
import { api, type Asset, type Bg, type Named, CATEGORY_LABELS, EXT_LABELS, formatBytes, formatClock, formatDuration, originalUrl, previewUrl } from "./api";
import { useInterval, useReducedMotion } from "./hooks";
import { IconClose, IconDownload, IconExternal, IconHeart, IconMore, IconPause, IconPlay, IconPlus, IconRefresh } from "./icons";

interface Props {
  assetId: string;
  selections: Named[];
  collections: Named[];
  categories: string[];
  onClose: () => void;
  onChanged: (asset: Asset) => void;
  onSelectionsChanged: () => void;
  onOpenSelection: (id: string) => void;
  onOpenAsset?: (id: string) => void;
}

export function Inspector(props: Props) {
  const { assetId, selections, collections, categories, onClose, onChanged } = props;
  const [asset, setAsset] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bg, setBg] = useState<Bg>("checker");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tagDraft, setTagDraft] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [menu, setMenu] = useState<"" | "selection" | "more">("");
  const [newName, setNewName] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const headRef = useRef<HTMLHeadingElement>(null);

  const load = (silent = false) =>
    api
      .asset(assetId)
      .then((a) => {
        setAsset(a);
        setError(null);
        if (!silent) {
          setTitle(a.title);
          setDescription(a.description);
        }
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    setAsset(null);
    setMenu("");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  const pending = !!asset && (asset.version.analysis_status === "pending" || asset.version.analysis_status === "running" || asset.preview.status === "pending");
  useInterval(() => load(true), 2000, pending);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (menu) setMenu("");
        else onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu, onClose]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2500);
    return () => window.clearTimeout(id);
  }, [toast]);

  const patch = async (body: Parameters<typeof api.patchAsset>[1], label: string) => {
    if (!asset) return;
    setSaving(label);
    try {
      const updated = await api.patchAsset(asset.id, body);
      setAsset(updated);
      onChanged(updated);
    } catch (e) {
      setToast(`No se pudo guardar: ${(e as Error).message}`);
    } finally {
      setSaving(null);
    }
  };

  if (error) {
    return (
      <aside className="inspector" aria-label="Ficha del recurso">
        <div className="inspector-head"><h2>Recurso</h2><button type="button" className="icon-btn" aria-label="Cerrar ficha" onClick={onClose}><IconClose /></button></div>
        <div className="inspector-body"><div className="notice warn">{error}</div></div>
      </aside>
    );
  }
  if (!asset) {
    return <aside className="inspector" aria-label="Ficha del recurso" aria-busy="true"><div className="inspector-head"><h2>Cargando…</h2></div></aside>;
  }

  const s = asset.summary;
  const isAlpha = asset.preview.kind === "video_alpha";
  const alphaLabel = s.alpha_format === null ? null : s.alpha_format ? (s.alpha_used === false ? "Canal alfa opaco" : s.alpha_used ? "Sí" : "Canal alfa (uso sin medir)") : "No";
  const addTag = () => {
    const t = tagDraft.trim();
    if (!t) return;
    setTagDraft("");
    patch({ tags: [...asset.tags, t] }, "tags");
  };

  return (
    <aside className="inspector" aria-label="Ficha del recurso">
      <div className="inspector-head">
        <h2 ref={headRef}>
          <input
            aria-label="Título visible"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => title.trim() && title !== asset.title && patch({ title }, "title")}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </h2>
        <button type="button" className="icon-btn" aria-pressed={asset.favorite} aria-label={asset.favorite ? "Quitar de favoritos" : "Añadir a favoritos"} onClick={() => patch({ favorite: !asset.favorite }, "fav")}>
          <IconHeart filled={asset.favorite} />
        </button>
        <div className="menu">
          <button type="button" className="icon-btn" aria-label="Más acciones" aria-haspopup="menu" aria-expanded={menu === "more"} onClick={() => setMenu(menu === "more" ? "" : "more")}><IconMore /></button>
          {menu === "more" && (
            <div className="menu-list" role="menu">
              <button type="button" role="menuitem" onClick={() => { setMenu(""); api.reanalyze(asset.id).then((a) => { setAsset(a); setToast("Reanálisis en cola"); }); }}><IconRefresh />Volver a analizar</button>
              <div className="sep" />
              <div className="tiny" style={{ padding: "4px 12px" }}>Añadir a colección</div>
              {collections.length === 0 && <div className="tiny" style={{ padding: "4px 12px" }}>No hay colecciones todavía.</div>}
              {collections.map((c) => (
                <button type="button" role="menuitemcheckbox" aria-checked={asset.in_collections.includes(c.id)} key={c.id}
                  onClick={async () => {
                    if (asset.in_collections.includes(c.id)) await api.removeFromCollection(c.id, asset.id);
                    else await api.addToCollection(c.id, asset.id);
                    setMenu("");
                    load(true).then(() => setToast(asset.in_collections.includes(c.id) ? `Quitado de «${c.name}»` : `Añadido a «${c.name}»`));
                    props.onSelectionsChanged();
                  }}>
                  {asset.in_collections.includes(c.id) ? "✓ " : ""}{c.name}
                </button>
              ))}
            </div>
          )}
        </div>
        <button type="button" className="icon-btn inspector-close" aria-label="Cerrar ficha" onClick={onClose}><IconClose /></button>
      </div>

      <div className="inspector-body">
        <Player asset={asset} bg={bg} />

        {isAlpha && (
          <div>
            <h3 className="section-title">Vista previa</h3>
            <div className="bg-switch" role="group" aria-label="Fondo de la preview">
              <span>Fondo</span>
              {(["dark", "light", "checker"] as Bg[]).map((b) => (
                <button type="button" key={b} className={`swatch ${b}`} aria-pressed={bg === b} aria-label={{ dark: "Fondo oscuro", light: "Fondo claro", checker: "Fondo cuadriculado" }[b]} onClick={() => setBg(b)} />
              ))}
            </div>
          </div>
        )}

        {asset.version.analysis_status === "failed" && (
          <div className="notice warn">Análisis fallido: {asset.version.analysis_error ?? "sin detalle"}. <button type="button" className="btn small" onClick={() => api.reanalyze(asset.id).then(setAsset)}>Reintentar</button></div>
        )}
        {asset.preview.status === "failed" && asset.version.analysis_status === "done" && (
          <div className="notice warn">
            Preview fallida: {Object.values(asset.derivatives).filter((d) => d.status === "failed").map((d) => d.error).join("; ") || "sin detalle"}
            <div style={{ marginTop: 6 }}><button type="button" className="btn small" onClick={() => api.reanalyze(asset.id).then(setAsset)}>Regenerar</button></div>
          </div>
        )}
        {asset.archived && (
          <div className="notice">
            <strong>Dentro del pack, sin extraer.</strong> La ficha existe con identidad provisional (crc32 + tamaño); el hash, el análisis y las previews llegan al extraer.
            <div style={{ marginTop: 8 }} className="row">
              <button type="button" className="btn small primary" disabled={!asset.extractable} onClick={async () => { try { const r = await api.extractAsset(asset.id); setToast(r.message ?? "Extracción en cola"); load(true); } catch (e) { setToast((e as Error).message); } }}>Extraer y analizar</button>
              <span className="tiny">{formatBytes(asset.version.size)} a la caché</span>
            </div>
          </div>
        )}
        {!asset.available && !asset.archived && !asset.remote_available && (
          <div className="notice warn">La fuente está desconectada: la ficha y las previews se conservan, pero el original no puede obtenerse ahora.</div>
        )}
        {!asset.available && !asset.archived && asset.remote_available && (
          <div className="notice">El original no está en este equipo, pero sí en tu Google Drive: se descarga en streaming desde allí.</div>
        )}
        {asset.duplicate_of && (
          <div className="notice">Mismos bytes que otra ficha (duplicado confirmado por SHA-256). Se conserva porque tiene ediciones o pertenencias. <button type="button" className="btn ghost small" onClick={() => props.onOpenAsset?.(asset.duplicate_of!)}>Ver la ficha principal</button></div>
        )}
        {asset.locations.length > 1 && !asset.duplicate_of && (
          <div className="notice">{asset.version.identity_kind === "sha256" ? "Mismos bytes en varias ubicaciones (confirmado por hash)." : "Candidato a duplicado: varias entradas con el mismo crc32 y tamaño; se confirmará al extraer."}</div>
        )}
        {asset.version.media_kind === "other" && (
          <div className="notice">
            <div><strong>{EXT_LABELS[asset.version.ext] ?? `Archivo ${asset.version.ext.toUpperCase()}`}</strong> · sin preview genérica{asset.preview.kind === "lut_demo" ? "; abajo, demostración sobre una imagen sintética" : ""}.</div>
            {asset.required_app && <div className="tiny" style={{ marginTop: 4 }}>Aplicación necesaria: {asset.required_app}</div>}
            {asset.lut && <div className="tiny" style={{ marginTop: 4 }}>LUT {asset.lut.size_3d ? `3D ${asset.lut.size_3d}³` : asset.lut.size_1d ? `1D ${asset.lut.size_1d}` : ""}{asset.lut.title ? ` · «${asset.lut.title}»` : ""} (cabecera del archivo)</div>}
            {asset.provider_preview && (
              <div style={{ marginTop: 8 }}>
                <div className="tiny">Preview suministrada por el proveedor (archivo hermano):</div>
                <button type="button" className="btn ghost small" onClick={() => props.onOpenAsset?.(asset.provider_preview!.asset_id)}>{asset.provider_preview.title}</button>
                {asset.provider_preview.thumb_url && <img src={asset.provider_preview.thumb_url} alt="" style={{ width: "100%", borderRadius: 10, marginTop: 6 }} />}
              </div>
            )}
          </div>
        )}

        <div className="desc">
          <textarea
            aria-label="Descripción"
            placeholder="Describe para qué sirve este recurso…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => description !== asset.description && patch({ description }, "desc")}
          />
          <div className="hint">
            {asset.description_source === "human" ? "Descripción editada a mano." : asset.description_source === "inferred" ? "Descripción inferida, revísala." : "Sin descripción todavía."}
            {saving === "desc" && " Guardando…"}
          </div>
        </div>

        <dl className="facts">
          <Fact label="Duración" value={s.duration_s !== null ? formatDuration(s.duration_s) : null} pendingLabel={["image", "other"].includes(asset.version.media_kind) ? "n/a" : asset.archived ? "sin extraer" : undefined} status={asset.version.analysis_status} />
          <Fact label="Resolución" value={s.width && s.height ? `${s.width} × ${s.height}` : null} pendingLabel={["audio", "other"].includes(asset.version.media_kind) ? "n/a" : asset.archived ? "sin extraer" : undefined} status={asset.version.analysis_status} />
          <Fact label="Fotogramas" value={s.fps ? `${s.fps} fps` : null} pendingLabel={asset.version.media_kind !== "video" ? "n/a" : asset.archived ? "sin extraer" : undefined} status={asset.version.analysis_status} />
          <Fact label="Transparencia" value={alphaLabel} pendingLabel={["audio", "other"].includes(asset.version.media_kind) ? "n/a" : asset.archived ? "sin extraer" : undefined} status={asset.version.analysis_status} />
          {asset.version.media_kind === "audio" && <Fact label="Muestreo" value={s.sample_rate ? `${s.sample_rate / 1000} kHz · ${s.bits ? `${s.bits} bit` : ""} ${s.channels ? (s.channels === 2 ? "estéreo" : `${s.channels} can.`) : ""}` : null} status={asset.version.analysis_status} />}
          {s.rotation ? <Fact label="Rotación" value={`${s.rotation}° (reproducción ${s.orientation === "vertical" ? "vertical" : "horizontal"})`} status="done" /> : null}
          <Fact label="Formato" value={[s.codec, s.pix_fmt].filter(Boolean).join(" · ") || asset.version.ext.toUpperCase()} status="done" />
          <Fact label="Tamaño" value={formatBytes(asset.version.size)} status="done" />
        </dl>

        <div>
          <h3 className="section-title">Categoría</h3>
          <div className="row">
            <select aria-label="Categoría" value={asset.category} onChange={(e) => patch({ category: e.target.value }, "cat")}>
              {categories.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c] ?? c}</option>)}
            </select>
            <span className="tiny">{asset.category_source === "inferred" ? "inferida de la carpeta" : "fijada a mano"}</span>
          </div>
        </div>

        <div>
          <h3 className="section-title">Etiquetas</h3>
          <div className="tags">
            {asset.tags.map((t) => (
              <span className="tag" key={t}>{t}<button type="button" aria-label={`Quitar etiqueta ${t}`} onClick={() => patch({ tags: asset.tags.filter((x) => x !== t) }, "tags")}>×</button></span>
            ))}
            <input
              className="tag-input"
              aria-label="Nueva etiqueta"
              placeholder="+ etiqueta"
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(); } }}
              onBlur={addTag}
            />
          </div>
        </div>

        <div className="actions">
          <div className="menu">
            <button type="button" className="btn primary block" aria-haspopup="menu" aria-expanded={menu === "selection"} onClick={() => setMenu(menu === "selection" ? "" : "selection")}>
              <IconPlus />Añadir a selección
            </button>
            {menu === "selection" && (
              <div className="menu-list up" role="menu" style={{ left: 0, right: 0 }}>
                {selections.length === 0 && <div className="tiny" style={{ padding: "6px 12px" }}>Aún no hay selecciones. Crea una:</div>}
                {selections.map((sel) => {
                  const inside = asset.in_selections.includes(sel.id);
                  return (
                    <button type="button" role="menuitemcheckbox" aria-checked={inside} key={sel.id}
                      onClick={async () => {
                        if (inside) await api.removeFromSelection(sel.id, asset.id);
                        else await api.addToSelection(sel.id, asset.id);
                        setMenu("");
                        await load(true);
                        props.onSelectionsChanged();
                        setToast(inside ? `Quitado de «${sel.name}»` : `Añadido a «${sel.name}»`);
                      }}>
                      {inside ? "✓ " : ""}{sel.name}<span className="tiny" style={{ marginLeft: "auto" }}>{sel.count ?? 0}</span>
                    </button>
                  );
                })}
                <div className="sep" />
                <form onSubmit={async (e) => {
                  e.preventDefault();
                  const name = newName.trim();
                  if (!name) return;
                  const created = await api.createSelection(name);
                  await api.addToSelection(created.id, asset.id);
                  setNewName("");
                  setMenu("");
                  await load(true);
                  props.onSelectionsChanged();
                  setToast(`Selección «${name}» creada`);
                }}>
                  <input className="input" placeholder="Nueva selección…" aria-label="Nombre de la nueva selección" value={newName} onChange={(e) => setNewName(e.target.value)} />
                  <button type="submit" className="btn small">Crear</button>
                </form>
              </div>
            )}
          </div>
          {asset.in_selections.length > 0 && (
            <div className="tiny">En {asset.in_selections.length === 1 ? "la selección" : "las selecciones"}: {asset.in_selections.map((id) => {
              const sel = selections.find((x) => x.id === id);
              return <button key={id} type="button" className="btn ghost small" onClick={() => props.onOpenSelection(id)}>{sel?.name ?? "…"}</button>;
            })}</div>
          )}
          <a className="btn block" href={originalUrl(asset)} download={asset.locations[0]?.file_name} aria-disabled={!asset.available && !asset.extractable && !asset.remote_available} onClick={(e) => !asset.available && !asset.extractable && !asset.remote_available && e.preventDefault()}>
            <IconDownload />{asset.archived ? "Extraer y descargar original" : !asset.available && asset.remote_available ? "Descargar original desde Drive" : "Descargar original"}
          </a>
          <a className="btn ghost block" href={originalUrl(asset, true)} target="_blank" rel="noreferrer" aria-disabled={!asset.available && !asset.remote_available} onClick={(e) => !asset.available && !asset.remote_available && e.preventDefault()}>
            <IconExternal />Ver original
          </a>
          {asset.in_drive ? (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="tiny">Copia verificada en Google Drive{asset.locations.find((l) => l.kind === "drive")?.verified_at ? ` · ${new Date(asset.locations.find((l) => l.kind === "drive")!.verified_at!).toLocaleDateString()}` : ""}</span>
              <button type="button" className="btn ghost small" onClick={async () => { try { const r = await api.driveVerifyAsset(asset.id); setToast(r.ok ? "Copia en Drive verificada" : "La copia en Drive no coincide o falta"); load(true); } catch (e) { setToast((e as Error).message); } }}>Comprobar en Drive</button>
            </div>
          ) : (
            <button type="button" className="btn ghost small" disabled={!asset.available} title={asset.available ? "" : "El original no está en este equipo; no se puede subir desde aquí"} onClick={async () => { try { const r = await api.driveUploadAsset(asset.id); setToast(r.message ?? "Subida a Drive en cola (reanudable, verificada por md5)"); } catch (e) { setToast((e as Error).message); } }}>Copiar a Drive</button>
          )}
          {asset.available && asset.locations.some((l) => l.kind === "pack" && l.status === "available") && (
            <button type="button" className="btn ghost small" onClick={async () => { const r = await api.releaseAsset(asset.id); setToast(`Copia extraída liberada (${r.released})`); load(true); }}>Liberar copia extraída de la caché</button>
          )}
        </div>

        <div className="notice">
          <div className="tiny">Archivo original</div>
          {asset.locations.map((l) => (
            <div key={l.id} className="path">
              {l.kind === "pack" ? `${l.pack_label ?? "pack"} › ${l.inner_path}` : l.kind === "drive" ? `Google Drive › ${l.file_name}` : `${l.source_label} / ${l.rel_path}`}
              {l.status === "offline" ? " · offline" : l.status === "archived" ? " · en el ZIP" : l.kind === "pack" ? " · extraído" : l.kind === "drive" ? " · remoto" : ""}
              {l.entry_error ? ` · error: ${l.entry_error}` : ""}
            </div>
          ))}
          <div className="tiny" style={{ marginTop: 6 }}>
            {asset.version.identity_kind === "sha256" ? <>SHA-256 <code>{asset.version.sha256.slice(0, 16)}…</code></> : <>Identidad provisional <code>{asset.version.sha256}</code> (sin verificar por hash)</>}
          </div>
        </div>
        {toast && <div className="notice ok" role="status">{toast}</div>}
      </div>
    </aside>
  );
}

function Fact({ label, value, status, pendingLabel }: { label: string; value: string | null; status: string; pendingLabel?: string }) {
  let text: string;
  let pending = false;
  if (value) text = value;
  else if (pendingLabel) { text = pendingLabel; pending = true; }
  else if (status === "failed") { text = "no medido (error)"; pending = true; }
  else if (status === "done") { text = "no disponible"; pending = true; }
  else { text = "pendiente"; pending = true; }
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd className={pending ? "pending" : undefined}>{text}</dd>
    </div>
  );
}

function Player({ asset, bg }: { asset: Asset; bg: Bg }) {
  const reduced = useReducedMotion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState<number>(asset.summary.duration_s ?? 0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setPlaying(false);
    setTime(0);
    setFailed(false);
    setDur(asset.summary.duration_s ?? 0);
  }, [asset.id, bg]);

  const media = () => videoRef.current ?? audioRef.current;
  const toggle = () => {
    const m = media();
    if (!m) return;
    if (m.paused) m.play().catch(() => setFailed(true));
    else m.pause();
  };
  const seek = (t: number) => {
    const m = media();
    if (m) m.currentTime = t;
    setTime(t);
  };
  const common = {
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => setTime(e.currentTarget.currentTime),
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLMediaElement>) => Number.isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration),
    onError: () => setFailed(true),
  };

  if (asset.preview.status === "archived") {
    return <div className="player"><div className="state">Sin extraer del pack: no hay preview todavía.</div></div>;
  }
  if (asset.preview.kind === "lut_demo") {
    return asset.lut_demo_url
      ? <div><div className="player bg-dark"><img src={asset.lut_demo_url} alt="Antes y después del LUT sobre una imagen de referencia sintética" /></div><div className="tiny" style={{ marginTop: 6 }}>Demostración: izquierda sin LUT, derecha con LUT, sobre una imagen sintética. No es tu material.</div></div>
      : <div className="player"><div className="state">{asset.preview.status === "failed" ? "No se pudo aplicar el LUT (archivo no compatible)." : "Generando demostración del LUT…"}</div></div>;
  }
  if (asset.preview.status === "pending") {
    return <div className="player"><div className="state">{asset.version.analysis_status === "done" ? "Generando preview…" : asset.available ? "Analizando el archivo…" : "Original no disponible: análisis pendiente."}</div></div>;
  }
  if (asset.preview.status === "failed" || failed) {
    return <div className="player"><div className="state failed">Preview no disponible{failed ? " (el navegador no pudo reproducirla)" : ""}.</div></div>;
  }
  if (asset.preview.kind === "none") {
    return <div className="player"><div className="state">Sin preview para {asset.version.ext.toUpperCase()}. El original se puede descargar.</div></div>;
  }
  if (asset.preview.kind === "image") {
    return <div className={`player bg-${bg}`}><img src={previewUrl(asset)} alt={asset.title} /></div>;
  }
  if (asset.preview.kind === "audio") {
    return (
      <div className="audio-player">
        <audio ref={audioRef} src={previewUrl(asset)} preload="metadata" {...common} />
        <div className="wave" role="slider" aria-label="Posición" aria-valuemin={0} aria-valuemax={dur} aria-valuenow={time} tabIndex={0}
          onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * dur); }}
          onKeyDown={(e) => { if (e.key === "ArrowRight") seek(Math.min(dur, time + 1)); if (e.key === "ArrowLeft") seek(Math.max(0, time - 1)); if (e.key === " ") { e.preventDefault(); toggle(); } }}>
          {asset.waveform_url && <img src={asset.waveform_url} alt="" />}
          <div className="cursor" style={{ left: `${dur ? (time / dur) * 100 : 0}%` }} />
        </div>
        <Transport playing={playing} time={time} dur={dur} onToggle={toggle} onSeek={seek} />
      </div>
    );
  }
  const isAlpha = asset.preview.kind === "video_alpha";
  return (
    <div>
      <div className={`player bg-${isAlpha ? bg : "dark"}`}>
        <video ref={videoRef} key={`${asset.id}-${bg}`} src={previewUrl(asset, bg)} preload="metadata" loop={!reduced} playsInline muted={false} {...common} />
      </div>
      <div style={{ marginTop: 10 }}>
        <Transport playing={playing} time={time} dur={dur} onToggle={toggle} onSeek={seek} />
      </div>
    </div>
  );
}

function Transport({ playing, time, dur, onToggle, onSeek }: { playing: boolean; time: number; dur: number; onToggle: () => void; onSeek: (t: number) => void }) {
  return (
    <div className="transport">
      <button type="button" className="play" aria-label={playing ? "Pausar" : "Reproducir"} onClick={onToggle}>{playing ? <IconPause /> : <IconPlay />}</button>
      <span className="time">{formatClock(time)} / {formatClock(dur)}</span>
      <input type="range" aria-label="Posición" min={0} max={dur || 0} step={0.01} value={Math.min(time, dur || 0)} onChange={(e) => onSeek(Number(e.target.value))} />
    </div>
  );
}
