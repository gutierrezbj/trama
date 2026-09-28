import { useState } from "react";
import { api } from "./api";
import { useAsync, useInterval } from "./hooks";

/** Nombre legible del modelo: «local:qwen/qwen3-vl-8b» → «Qwen3-VL 8B · Mac (gratis)». */
function modelName(m: string): string {
  const provider = m.split(":")[0];
  const id = m.slice(m.indexOf(":") + 1);
  if (provider === "local") return `${id === "qwen/qwen3-vl-8b" ? "Qwen3-VL 8B" : id.split("/").pop()} · Mac (gratis)`;
  return id;
}

function money(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v > 0 && v < 0.01) return `${(v * 100).toFixed(2)} ¢`;
  return `${v.toFixed(2)} $`;
}

/**
 * Nivel 2, prueba antes de gastar: la misma muestra pasa por varios modelos de visión; aquí se
 * comparan lado a lado, con coste y tiempo medidos y su proyección a toda la biblioteca, y se vota.
 */
export function IAView({ onOpenAsset }: { onOpenAsset: (id: string) => void }) {
  const status = useAsync(() => api.aiStatus(), []);
  const run = useAsync(() => api.aiLatest(), []);
  const [msg, setMsg] = useState<string | null>(null);
  const r = run.data;
  const running = !!r && (r.status === "queued" || r.status === "running");
  useInterval(() => run.reload(true), 3000, running);

  const start = async () => {
    setMsg(null);
    try {
      await api.aiTest();
      run.reload(true);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const vote = async (versionId: string, winner: string) => {
    if (!r) return;
    await api.aiVote(r.id, versionId, winner);
    run.reload(true);
  };

  const s = status.data;
  const answered = r ? r.items.reduce((n, it) => n + Object.keys(it.results).length, 0) : 0;
  const expected = r ? r.items.length * r.models.length : 0;
  const voted = r ? r.items.filter((it) => it.vote).length : 0;

  return (
    <>
      <div className="view-head">
        <h1>IA de visión</h1>
        <p>Antes de gastar nada en toda la biblioteca: la misma muestra pasa por varios modelos, comparas lo que dicen, votas y ves lo que costaría de verdad.</p>
      </div>

      <div className="panel" style={{ marginBottom: 18 }}>
        <div className="ai-head">
          <div>
            <h2>{r ? (running ? "Prueba en marcha…" : "Última prueba") : "Prueba de 50 recursos"}</h2>
            <p className="tiny">
              Modelos: {(r?.models ?? s?.default_models ?? []).map(modelName).join(" · ")}
              {s && !s.local && " · LM Studio del Mac sin configurar"}
              {s && !s.openai && " · sin clave de OpenAI"}
            </p>
          </div>
          <div className="ai-actions">
          {r && !running && r.summary.some((m) => m.errors > 0) && (
            <button type="button" className="btn" onClick={async () => { await api.aiRetry(r.id); run.reload(true); }}>
              Reintentar las {r.summary.reduce((n, m) => n + m.errors, 0)} que fallaron
            </button>
          )}
          <button type="button" className="btn primary" disabled={running || !s || (!s.local && !s.openai)} onClick={start}>
            {r ? "Lanzar otra prueba" : "Lanzar prueba"}
          </button>
          </div>
        </div>
        {running && <div className="progress" aria-label="Progreso"><div style={{ width: `${Math.round((answered / Math.max(1, expected)) * 100)}%` }} /></div>}
        {running && <p className="tiny">{answered} de {expected} respuestas. El modelo del Mac es el más lento: deja el Mac encendido con LM Studio abierto.</p>}
        {msg && <div className="notice warn">{msg}</div>}

        {r && (
          <div className="ai-summary">
            {r.summary.map((m) => (
              <div key={m.model} className="ai-model">
                <strong>{modelName(m.model)}</strong>
                <dl>
                  <div><dt>Esta prueba</dt><dd>{money(m.cost_usd)}</dd></div>
                  <div><dt>Toda la biblioteca ({r.visual_total})</dt><dd>{money(m.projected_cost_usd)}</dd></div>
                  <div><dt>Por recurso</dt><dd>{m.avg_seconds ?? "—"} s</dd></div>
                  <div><dt>Tiempo total</dt><dd>{m.projected_hours ?? "—"} h</dd></div>
                  <div><dt>Errores</dt><dd>{m.errors}</dd></div>
                  <div><dt>Tus votos</dt><dd className="wins">{m.wins}</dd></div>
                </dl>
              </div>
            ))}
            <p className="tiny">
              Has votado {voted} de {r.items.length}{r.ties ? ` · ${r.ties} empates` : ""}{r.none ? ` · ${r.none} sin acierto` : ""}. Coste de OpenAI calculado con los tokens reales de cada respuesta.
            </p>
          </div>
        )}
      </div>

      {r?.items.map((it, i) => (
        <article key={it.version_id} className="ai-item">
          <div className="ai-item-head">
            <span className="tiny">{i + 1}</span>
            <button type="button" className="linklike" onClick={() => onOpenAsset(it.asset_id)}>{it.title}</button>
            <span className="tiny">{it.auto_tags.slice(0, 6).join(" · ")}</span>
          </div>
          <img className="ai-sheet" src={it.sheet_url} alt={`Tres fotogramas de ${it.title}`} loading="lazy" />
          <div className="ai-results">
            {r.models.map((m) => {
              const res = it.results[m];
              return (
                <div key={m} className={`ai-result${it.vote === m ? " won" : ""}`}>
                  <div className="tiny">{modelName(m)}{res && !res.error ? ` · ${res.seconds} s` : ""}</div>
                  {!res && <p className="tiny">Pendiente…</p>}
                  {res?.error && <p className="tiny warn-text">Error: {res.error}</p>}
                  {res && !res.error && (
                    <>
                      <p>{res.description}</p>
                      <div className="tag-row">{res.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>
                    </>
                  )}
                  <button type="button" className="btn small" aria-pressed={it.vote === m} disabled={!res || !!res.error} onClick={() => vote(it.version_id, m)}>
                    {it.vote === m ? "✓ La mejor" : "Esta es la mejor"}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="ai-item-foot">
            <button type="button" className="btn ghost small" aria-pressed={it.vote === "tie"} onClick={() => vote(it.version_id, "tie")}>{it.vote === "tie" ? "✓ " : ""}Empate</button>
            <button type="button" className="btn ghost small" aria-pressed={it.vote === "none"} onClick={() => vote(it.version_id, "none")}>{it.vote === "none" ? "✓ " : ""}Ninguna acierta</button>
          </div>
        </article>
      ))}
    </>
  );
}
