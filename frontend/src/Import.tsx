import { useEffect, useState } from "react";
import { api, type Config, type Import, type Job } from "./api";
import { useAsync, useInterval } from "./hooks";
import { IconFolder } from "./icons";

interface Props {
  config: Config | null;
  busy: boolean;
  onImported: () => void;
}

export function ImportView({ config, busy, onImported }: Props) {
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
  const jobs = useAsync(() => api.jobs("running,queued,failed,cancelled"), []);
  useInterval(() => { imports.reload(true); jobs.reload(true); }, 2000, busy || (imports.data ?? []).some((i) => i.status === "queued" || i.status === "running"));

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

  const crumbs = path ? path.split("/") : [];
  const source = sources.find((s) => s.id === sourceId);

  return (
    <>
      <div className="view-head"><h1>Incorporar</h1><p>Elige una carpeta dentro de las raíces permitidas. Los originales no se mueven ni se modifican.</p></div>
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
                  <button type="button" key={d.path} onClick={() => setPath(d.path)}><IconFolder />{d.name}<span className="n">{d.media_files > 0 ? `${d.media_files} archivos` : ""}</span></button>
                ))}
                {browse.data && browse.data.dirs.length === 0 && <div className="tiny" style={{ padding: 8 }}>Sin subcarpetas.</div>}
              </div>
              <div className="tiny">{browse.data ? `${browse.data.media_files} archivos multimedia en esta carpeta (más los de subcarpetas).` : ""}</div>
              {error && <div className="notice warn">{error}</div>}
              <button type="button" className="btn primary block" disabled={launching || !browse.data} onClick={start}>Incorporar «{crumbs[crumbs.length - 1] ?? source.label}»</button>
            </>
          )}
        </div>

        <div className="panel">
          <h2>Lotes</h2>
          {imports.data && imports.data.length === 0 && <div className="tiny">Todavía no se ha incorporado nada.</div>}
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
  const labels: Record<string, string> = { import: "Incorporación", analyze: "Análisis", derive: "Previews" };
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
