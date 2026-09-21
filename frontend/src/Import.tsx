import { useEffect, useState } from "react";
import { api, type Config, type Import, type Job, type Pack, type PackFolder, formatBytes } from "./api";
import { useAsync, useInterval } from "./hooks";
import { IconBox, IconFolder } from "./icons";

interface Props {
  config: Config | null;
  busy: boolean;
  onImported: () => void;
  onOpenPack: (packId: string) => void;
}

export function ImportView({ config, busy, onImported, onOpenPack }: Props) {
  const sources = config?.sources ?? [];
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  useEffect(() => {
    if (!sourceId && sources.length) setSourceId(sources.find((s) => s.exists)?.id ?? sources[0].id);
  }, [sources, sourceId]);

  const browse = useAsync(async () => (sourceId ? api.browse(sourceId, path) : null), [sourceId, path]);
  const imports = useAsync(() => api.imports(), []);
  const packs = useAsync(() => api.packs(), []);
  const storage = useAsync(() => api.storage(), []);
  const jobs = useAsync(() => api.jobs("running,queued,failed,cancelled"), []);
  const active = busy || (imports.data ?? []).some((i) => i.status === "queued" || i.status === "running") || (packs.data ?? []).some((p) => p.active_job);
  useInterval(() => { imports.reload(true); jobs.reload(true); packs.reload(true); storage.reload(true); browse.reload(true); }, 2500, active);

  const start = async () => {
    if (!sourceId) return;
    setLaunching(true);
    setError(null);
    try {
      await api.createImport(sourceId, path);
      imports.reload();
      onImported();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLaunching(false);
    }
  };
  const indexZips = async (zipPath: string) => {
    if (!sourceId) return;
    setError(null);
    try {
      await api.indexPacks(sourceId, zipPath);
      packs.reload();
      browse.reload(true);
      onImported();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const crumbs = path ? path.split("/") : [];
  const source = sources.find((s) => s.id === sourceId);
  const st = storage.data;

  return (
    <>
      <div className="view-head"><h1>Incorporar</h1><p>Carpetas y packs ZIP dentro de las raíces permitidas. Los originales no se mueven ni se modifican; los ZIP se leen sin extraerlos hasta que tú lo pides.</p></div>
      {config && !config.tools.ok && <div className="notice warn">FFmpeg no disponible: {config.tools.error}. Los archivos se catalogarán, pero sin análisis ni previews.</div>}
      <div className="import-grid">
        <div className="panel">
          <h2>Fuentes locales</h2>
          {sources.length === 0 && <div className="notice warn">No hay raíces permitidas. Define <code>TRAMA_ALLOWED_ROOTS</code> en el archivo .env y reinicia el servidor.</div>}
          <div className="source-list">
            {sources.map((s) => (
              <button type="button" key={s.id} aria-pressed={s.id === sourceId} disabled={!s.exists} onClick={() => { setSourceId(s.id); setPath(""); }}>
                <strong>{s.label}</strong>
                <span className="path">{s.path}</span>
                <span className="tiny">{s.exists ? `${s.locations} archivos conocidos` : "no accesible ahora (fuente desconectada)"}</span>
              </button>
            ))}
          </div>
          {source && (
            <>
              <h2>Carpeta</h2>
              <div className="crumbs">
                <button type="button" onClick={() => setPath("")}>{source.label}</button>
                {crumbs.map((c, i) => (
                  <span key={i}>/ <button type="button" onClick={() => setPath(crumbs.slice(0, i + 1).join("/"))}>{c}</button></span>
                ))}
              </div>
              {browse.error && <div className="notice warn">{browse.error}</div>}
              <div className="dir-list">
                {browse.data?.dirs.map((d) => (
                  <button type="button" key={d.path} onClick={() => setPath(d.path)}><IconFolder />{d.name}<span className="n">{[d.media_files > 0 ? `${d.media_files} archivos` : "", d.zip_files > 0 ? `${d.zip_files} ZIP` : ""].filter(Boolean).join(" · ")}</span></button>
                ))}
                {browse.data?.zips.map((z) => (
                  <div key={z.path} className="zip-row">
                    <IconBox />
                    <span className="zip-name" title={z.name}>{z.name}</span>
                    <span className="n">{formatBytes(z.size)}{z.entries_media !== null ? ` · ${z.entries_media} recursos` : ""}</span>
                    {z.pack_id ? (
                      <button type="button" className="btn small" onClick={() => onOpenPack(z.pack_id!)}>{z.pack_status === "indexed" ? "Ver pack" : z.pack_status}</button>
                    ) : (
                      <button type="button" className="btn small" onClick={() => indexZips(z.path)}>Indexar</button>
                    )}
                  </div>
                ))}
                {browse.data && browse.data.dirs.length === 0 && browse.data.zips.length === 0 && <div className="tiny" style={{ padding: 8 }}>Sin subcarpetas ni ZIP.</div>}
              </div>
              <div className="tiny">{browse.data ? `${browse.data.media_files} archivos multimedia sueltos en esta carpeta (más los de subcarpetas).` : ""}</div>
              {error && <div className="notice warn">{error}</div>}
              <div className="row" style={{ flexWrap: "wrap" }}>
                <button type="button" className="btn primary" disabled={launching || !browse.data} onClick={start}>Incorporar carpeta «{crumbs[crumbs.length - 1] ?? source.label}»</button>
                {browse.data && browse.data.zips.some((z) => !z.pack_id) && (
                  <button type="button" className="btn" onClick={() => indexZips(path)}>Indexar los {browse.data.zips.filter((z) => !z.pack_id).length} ZIP sin indexar</button>
                )}
              </div>
            </>
          )}
        </div>

        <div className="panel">
          <h2>Packs indexados</h2>
          {st && (
            <div className="storage">
              <div className="row between tiny"><span>Caché de extracción</span><span>{formatBytes(st.cache_bytes)} de {formatBytes(st.cache_max_bytes)}</span></div>
              <div className="progress"><div style={{ width: `${Math.min(100, (st.cache_bytes / st.cache_max_bytes) * 100)}%` }} /></div>
              <div className="tiny">Disco libre {formatBytes(st.disk_free_bytes)} (mínimo reservado {formatBytes(st.min_free_bytes)}) · derivados {formatBytes(st.derivatives_bytes)}</div>
            </div>
          )}
          {packs.data && packs.data.length === 0 && <div className="tiny">Ningún ZIP indexado todavía. Indexar lee el índice del ZIP sin extraer nada.</div>}
          <div className="job-list">
            {(packs.data ?? []).map((p) => <PackRow key={p.id} pack={p} onOpen={() => onOpenPack(p.id)} />)}
          </div>

          <h2>Lotes de carpetas</h2>
          {imports.data && imports.data.length === 0 && <div className="tiny">Todavía no se ha incorporado ninguna carpeta.</div>}
          <div className="job-list">
            {(imports.data ?? []).map((imp) => <ImportRow key={imp.id} imp={imp} sources={sources} onCancel={() => api.cancelImport(imp.id).then(() => imports.reload(true))} />)}
          </div>
          <h2>Trabajos</h2>
          <JobsPanel jobs={jobs.data ?? []} onRetry={(id) => api.retryJob(id).then(() => jobs.reload(true))} onCancel={(id) => api.cancelJob(id).then(() => jobs.reload(true))} onRetryAll={() => api.retryFailed().then(() => jobs.reload(true))} />
        </div>
      </div>
    </>
  );
}

function PackRow({ pack, onOpen }: { pack: Pack; onOpen: () => void }) {
  const status = pack.active_job ? (pack.active_job.kind === "extract" ? "extrayendo" : "indexando") : { pending: "pendiente", indexing: "indexando", indexed: "indexado", failed: "fallido", offline: "ZIP no accesible" }[pack.status];
  return (
    <div className="job">
      <div>
        <strong>{pack.label}</strong>
        <div className="tiny">{pack.entries_media} recursos · {pack.extracted} extraídos ({formatBytes(pack.extracted_bytes)}) · {formatBytes(pack.bytes_total)} en total{pack.entries_unsafe ? ` · ${pack.entries_unsafe} entradas rechazadas` : ""}{pack.failed ? ` · ${pack.failed} con error` : ""}</div>
        {pack.active_job && <div className="progress" style={{ marginTop: 6 }}><div style={{ width: `${Math.round(pack.active_job.progress * 100)}%` }} /></div>}
        {pack.active_job?.message && <div className="tiny">{pack.active_job.message}</div>}
        {pack.error && <div className="err">{pack.error}</div>}
      </div>
      <div style={{ textAlign: "right" }}>
        <div className={`status ${pack.active_job ? "running" : pack.status === "failed" || pack.status === "offline" ? "failed" : "done"}`}>{status}</div>
        <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={onOpen}>Carpetas</button>
      </div>
    </div>
  );
}

export function PackDetail({ id, onBack, onExplore }: { id: string; onBack: () => void; onExplore: (packId: string) => void }) {
  const pack = useAsync(() => api.pack(id), [id]);
  const [label, setLabel] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [depth, setDepth] = useState(3);
  const p = pack.data;
  useInterval(() => pack.reload(true), 2000, !!p?.active_job);
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setMsg(null);
    try {
      const r = (await fn()) as { message?: string; entries?: number; bytes?: number; released?: number };
      setMsg(r.message ?? (r.entries !== undefined ? `${done}: ${r.entries} entradas, ${formatBytes(r.bytes)}` : r.released !== undefined ? `${done}: ${r.released} copias liberadas` : done));
      pack.reload(true);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  if (pack.error) return <div className="notice warn">{pack.error}</div>;
  if (!p) return <div className="tiny">Cargando…</div>;
  const folders: PackFolder[] = (p.folders ?? []).filter((f) => f.depth <= depth);
  return (
    <>
      <div className="detail-head">
        <button type="button" className="btn ghost small" onClick={onBack}>← Incorporar</button>
        <h1>
          <input aria-label="Nombre del pack" value={label ?? p.label} size={Math.max(12, (label ?? p.label).length + 2)} onChange={(e) => setLabel(e.target.value)}
            onBlur={async () => { if (label && label.trim() && label !== p.label) { await api.patchPack(p.id, label.trim()); pack.reload(true); } setLabel(null); }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        </h1>
        <span className="muted">{p.entries_media} recursos · {p.extracted} extraídos · {formatBytes(p.bytes_total)}</span>
        <div className="row" style={{ marginLeft: "auto" }}>
          <button type="button" className="btn small" onClick={() => onExplore(p.id)}>Explorar recursos</button>
          <a className="btn small" href={`/api/packs/${p.id}/inventory.csv`}>Inventario CSV</a>
          <button type="button" className="btn small" onClick={() => act(() => api.reindexPack(p.id), "Reindexación en cola")}>Reindexar</button>
        </div>
      </div>
      <div className="tiny path" style={{ marginBottom: 12 }}>{p.rel_path}{p.zip_present ? "" : " · el ZIP no está accesible ahora"}</div>
      {p.active_job && <div className="notice">{p.active_job.kind === "extract" ? "Extrayendo" : "Indexando"}: {p.active_job.message ?? ""} ({Math.round(p.active_job.progress * 100)} %)</div>}
      {msg && <div className="notice" role="status">{msg}</div>}
      {p.error && <div className="notice warn">{p.error}</div>}
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="tiny">Profundidad</span>
        {[1, 2, 3, 4].map((d) => <button key={d} type="button" className="chip" aria-pressed={depth === d} onClick={() => setDepth(d)}>{d}</button>)}
      </div>
      <div className="folder-list">
        {folders.map((f) => (
          <div className="folder-row" key={f.path || "(raíz)"} style={{ paddingLeft: 12 + f.depth * 18 }}>
            <IconFolder />
            <span className="folder-name">{f.path ? f.path.split("/").pop() : "(todo el pack)"}</span>
            <span className="tiny">{f.media} recursos · {f.extracted} extraídos · {formatBytes(f.bytes)}{f.unsafe ? ` · ${f.unsafe} rechazadas` : ""}</span>
            <div className="ops">
              {f.extracted < f.media && <button type="button" className="btn small" disabled={!!p.active_job || !p.zip_present} onClick={() => act(() => api.extractPack(p.id, f.path), "Extracción en cola")}>Extraer</button>}
              {f.extracted > 0 && <button type="button" className="btn ghost small" onClick={() => { if (window.confirm("¿Liberar las copias extraídas de esta carpeta? El ZIP, las fichas y las previews se conservan.")) act(() => api.releasePack(p.id, f.path), "Liberado"); }}>Liberar</button>}
            </div>
          </div>
        ))}
      </div>
      {p.unsafe_entries && p.unsafe_entries.length > 0 && (
        <div className="notice warn" style={{ marginTop: 14 }}>
          Entradas rechazadas por seguridad ({p.entries_unsafe}):
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{p.unsafe_entries.map((e) => <li key={e.inner_path}><span className="path">{e.inner_path}</span> — {e.unsafe_reason}</li>)}</ul>
        </div>
      )}
      {p.failed_entries && p.failed_entries.length > 0 && (
        <div className="notice warn" style={{ marginTop: 14 }}>
          Entradas con error de extracción:
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{p.failed_entries.map((e) => <li key={e.id}><span className="path">{e.inner_path}</span> — {e.error}</li>)}</ul>
          <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={() => act(() => api.extractPack(p.id, "", p.failed_entries!.map((e) => e.id)), "Reintento en cola")}>Reintentar</button>
        </div>
      )}
    </>
  );
}

function ImportRow({ imp, sources, onCancel }: { imp: Import; sources: Config["sources"]; onCancel: () => void }) {
  const src = sources.find((s) => s.id === imp.source_id);
  const pct = imp.total_files ? Math.round((imp.processed / imp.total_files) * 100) : imp.status === "done" ? 100 : 0;
  const active = imp.status === "queued" || imp.status === "running";
  return (
    <div className="job">
      <div>
        <strong>{src?.label ?? imp.source_id}</strong>{imp.sub_path ? ` / ${imp.sub_path}` : ""}
        <div className="tiny">{imp.message ?? (imp.status === "running" ? `${imp.processed}/${imp.total_files} archivos` : imp.status)}</div>
        {active && <div className="progress" style={{ marginTop: 6 }}><div style={{ width: `${pct}%` }} /></div>}
      </div>
      <div style={{ textAlign: "right" }}>
        <div className={`status ${imp.status}`}>{{ queued: "en cola", running: "en curso", done: "hecho", failed: "fallido", cancelled: "cancelado" }[imp.status]}</div>
        {active && <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={onCancel}>Cancelar</button>}
      </div>
      {imp.errors.length > 0 && (
        <div className="err">
          {imp.errors.length} {imp.errors.length === 1 ? "archivo con error" : "archivos con error"}:
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{imp.errors.slice(0, 8).map((e, i) => <li key={i}><span className="path">{e.path}</span> — {e.error}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function JobsPanel({ jobs, onRetry, onCancel, onRetryAll }: { jobs: Job[]; onRetry: (id: string) => void; onCancel: (id: string) => void; onRetryAll: () => void }) {
  const failed = jobs.filter((j) => j.status === "failed");
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const labels: Record<string, string> = { import: "Incorporación", analyze: "Análisis", derive: "Previews", index_pack: "Índice de pack", extract: "Extracción" };
  return (
    <>
      <div className="tiny">{active.length} activos · {failed.length} fallidos {failed.length > 0 && <button type="button" className="btn small" style={{ marginLeft: 8 }} onClick={onRetryAll}>Reintentar todos</button>}</div>
      {jobs.length === 0 && <div className="tiny">Sin trabajos pendientes ni fallidos.</div>}
      <div className="job-list">
        {jobs.slice(0, 40).map((j) => (
          <div className="job" key={j.id}>
            <div>
              <strong>{labels[j.kind] ?? j.kind}</strong> {j.asset_title ? `· ${j.asset_title}` : ""}
              <div className="tiny">{j.message ?? ""}{j.attempts > 1 ? ` · intento ${j.attempts}` : ""}</div>
              {j.status === "running" && <div className="progress" style={{ marginTop: 6 }}><div style={{ width: `${Math.round(j.progress * 100)}%` }} /></div>}
            </div>
            <div style={{ textAlign: "right" }}>
              <div className={`status ${j.status}`}>{{ queued: "en cola", running: "en curso", done: "hecho", failed: "fallido", cancelled: "cancelado" }[j.status]}</div>
              {(j.status === "failed" || j.status === "cancelled") && <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={() => onRetry(j.id)}>Reintentar</button>}
              {(j.status === "running" || j.status === "queued") && <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={() => onCancel(j.id)}>Cancelar</button>}
            </div>
            {j.error && <div className="err">{j.error}</div>}
          </div>
        ))}
      </div>
    </>
  );
}
