import { useEffect, useState } from "react";
import { api, type Config, formatBytes } from "./api";
import { useAsync, useInterval } from "./hooks";
import { JobsPanel } from "./Import";

interface Props {
  config: Config | null;
  busy: boolean;
  notice?: string | null;
}

export function CopiasView({ config, busy, notice }: Props) {
  const drive = useAsync(() => api.driveStatus(), []);
  const backups = useAsync(() => api.backups(), []);
  const jobs = useAsync(() => api.jobs("running,queued,failed"), []);
  const [label, setLabel] = useState("");
  const [msg, setMsg] = useState<string | null>(notice ?? null);
  const [verify, setVerify] = useState<Record<string, string>>({});
  const active = busy || !!backups.data?.last_job && ["queued", "running"].includes(backups.data.last_job.status);
  useInterval(() => { backups.reload(true); jobs.reload(true); }, 2500, active);
  useEffect(() => { if (notice) setMsg(notice); }, [notice]);
  const d = drive.data;
  const driveJobs = (jobs.data ?? []).filter((j) => j.kind === "drive_upload" || j.kind === "backup");

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setMsg(null);
    try {
      const r = (await fn()) as Record<string, unknown>;
      setMsg(typeof r.message === "string" && r.message ? r.message : done);
      drive.reload(true);
      backups.reload(true);
      jobs.reload(true);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <>
      <div className="view-head"><h1>Copias y Drive</h1><p>Snapshots del catálogo con restauración ensayada, y copia de originales en una carpeta privada de tu Google Drive.</p></div>
      {msg && <div className="notice" role="status" style={{ marginBottom: 14 }}>{msg}</div>}
      <div className="import-grid">
        <div className="panel">
          <h2>Google Drive</h2>
          {drive.error && <div className="notice warn">{drive.error}</div>}
          {d && !d.configured && (
            <div className="notice">
              <strong>No configurado.</strong> TRAMA necesita un cliente OAuth propio (tipo «Aplicación de escritorio») creado en Google Cloud con la API de Drive activada. Descarga su <code>client_secret.json</code> y guárdalo en
              <div className="path" style={{ margin: "6px 0" }}>{config?.data_dir}\drive\client_secret.json</div>
              (o indica la ruta en <code>TRAMA_DRIVE_CLIENT_FILE</code>). Reinicia el servidor y vuelve aquí para conectar. URI de redirección a registrar: <code>{d.redirect_uri ?? "http://127.0.0.1:8765/api/drive/auth/callback"}</code>.
              <div className="tiny" style={{ marginTop: 6 }}>Alcance mínimo: {d.scope}. Las credenciales quedan solo en el servidor; no se comparte nada ni se crean enlaces públicos.</div>
            </div>
          )}
          {d && d.configured && !d.connected && (
            <div className="notice">
              <strong>Configurado, sin conectar.</strong> Autoriza el acceso con tu cuenta de Google; TRAMA solo podrá ver los archivos que ella misma cree en la carpeta «{d.folder_name}».
              <div style={{ marginTop: 8 }}>
                <button type="button" className="btn primary" onClick={async () => { try { const { url } = await api.driveAuthStart(); window.location.href = url; } catch (e) { setMsg((e as Error).message); } }}>Conectar con Google Drive</button>
              </div>
              {d.error && <div className="err" style={{ marginTop: 6 }}>{d.error}</div>}
            </div>
          )}
          {d && d.connected && (
            <div className="notice ok">
              <strong>Conectado</strong>{d.account ? ` como ${d.account}` : ""} · carpeta «{d.folder_name}» · {d.files ?? 0} originales subidos
              {d.quota && <div className="tiny">Uso de Drive: {formatBytes(d.quota.usage)}{d.quota.limit ? ` de ${formatBytes(d.quota.limit)}` : ""}</div>}
              {d.error && <div className="err" style={{ marginTop: 6 }}>{d.error}</div>}
              <div style={{ marginTop: 8 }} className="row">
                <button type="button" className="btn ghost small" onClick={() => { if (window.confirm("¿Desconectar Drive? Los archivos ya subidos siguen en tu Drive; TRAMA olvidará el token de acceso.")) act(() => api.driveDisconnect(), "Drive desconectado"); }}>Desconectar</button>
              </div>
            </div>
          )}
          <div className="tiny">Subir originales: desde la ficha de un recurso («Copiar a Drive») o desde una selección («Copiar la selección a Drive»). Cada subida es reanudable y se verifica por md5 antes de darse por buena. Un original que solo esté en un ordenador apagado no puede subirse desde el servidor: la ficha lo indica.</div>
        </div>

        <div className="panel">
          <h2>Snapshots del catálogo</h2>
          <div className="tiny">Copia consistente de la base de datos y los derivados en <span className="path">{backups.data?.dir}</span>. Se conservan los últimos {backups.data?.keep ?? "—"}. La caché de packs no se incluye (se reconstruye desde los ZIP). Restaurar: <code>python -m trama restore &lt;carpeta&gt;</code> con el servidor parado.</div>
          <div className="row">
            <input className="input" placeholder="Etiqueta (opcional)" aria-label="Etiqueta del snapshot" value={label} onChange={(e) => setLabel(e.target.value)} />
            <button type="button" className="btn primary" disabled={active} onClick={() => act(() => api.createBackup(label, false), "Snapshot en cola")}>Crear snapshot</button>
            <button type="button" className="btn" disabled={active || !d?.connected} title={d?.connected ? "" : "Requiere Drive conectado"} onClick={() => act(() => api.createBackup(label, true), "Snapshot en cola; se subirá a Drive al terminar")}>Crear y subir a Drive</button>
          </div>
          {backups.data?.last_job && ["queued", "running"].includes(backups.data.last_job.status) && (
            <div className="notice">{backups.data.last_job.message ?? "Creando snapshot…"}<div className="progress" style={{ marginTop: 6 }}><div style={{ width: `${Math.round((backups.data.last_job.progress ?? 0) * 100)}%` }} /></div></div>
          )}
          {backups.data?.last_job?.status === "failed" && <div className="notice warn">Último snapshot fallido: {backups.data.last_job.error}</div>}
          <div className="job-list">
            {(backups.data?.backups ?? []).map((b) => (
              <div className="job" key={b.id}>
                <div>
                  <strong>{b.path.split(/[\\/]/).pop()}</strong>
                  <div className="tiny">{new Date(b.created_at).toLocaleString()} · {b.assets} fichas · {b.derivatives_files} derivados ({formatBytes(b.derivatives_bytes)}) · catálogo {formatBytes(b.db_bytes)}</div>
                  {verify[b.id] && <div className="tiny">{verify[b.id]}</div>}
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className={`status ${b.present ? (b.status === "uploaded" ? "done" : "done") : "failed"}`}>{!b.present ? "falta en disco" : b.status === "uploaded" ? "en Drive" : "local"}</div>
                  <button type="button" className="btn small" style={{ marginTop: 6 }} onClick={async () => { const r = await api.verifyBackup(b.id); setVerify({ ...verify, [b.id]: r.ok ? `Íntegro: ${r.assets} fichas, ${r.derivatives_present}/${r.derivatives_files} derivados presentes` : `NO válido: ${r.error}` }); }}>Verificar</button>
                </div>
              </div>
            ))}
            {backups.data && backups.data.backups.length === 0 && <div className="tiny">Todavía no hay snapshots.</div>}
          </div>
          <h2>Trabajos de copia</h2>
          <JobsPanel jobs={driveJobs} onRetry={(id) => api.retryJob(id).then(() => jobs.reload(true))} onCancel={(id) => api.cancelJob(id).then(() => jobs.reload(true))} onRetryAll={() => api.retryFailed().then(() => jobs.reload(true))} />
        </div>
      </div>
    </>
  );
}
