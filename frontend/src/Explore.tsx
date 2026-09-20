import { useMemo, useRef, useState } from "react";
import { api, type Asset, type AssetFilters, CATEGORY_LABELS } from "./api";
import { AssetCard } from "./AssetCard";
import { useAsync, useDebounced, useInterval, useReducedMotion } from "./hooks";
import { IconSliders } from "./icons";

export interface ExploreState {
  alpha: boolean;
  vertical: boolean;
  short: boolean;
  categories: string[];
  availability: "" | "available" | "offline";
  analysis: "" | "pending" | "failed" | "done";
  sort: "recent" | "title" | "duration" | "size";
  offset: number;
}

export const initialExplore: ExploreState = {
  alpha: false, vertical: false, short: false, categories: [], availability: "", analysis: "", sort: "recent", offset: 0,
};

interface Props {
  title: string;
  subtitle?: string;
  query: string;
  state: ExploreState;
  onState: (s: ExploreState) => void;
  fixed?: Partial<AssetFilters>;
  categories: string[];
  selectedId: string | null;
  onOpen: (asset: Asset, el: HTMLElement) => void;
  onToggleFavorite: (asset: Asset) => Promise<void>;
  busy: boolean;
  refreshKey: number;
  showFilters?: boolean;
  emptyHint?: string;
}

const PAGE = 60;

export function Explore(props: Props) {
  const { query, state, onState, fixed, selectedId, onOpen, onToggleFavorite, busy, refreshKey, categories } = props;
  const debounced = useDebounced(query, 220);
  const reduced = useReducedMotion();
  const [hover, setHover] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const filters = useMemo<AssetFilters>(
    () => ({
      q: debounced,
      alpha: state.alpha ? true : undefined,
      orientation: state.vertical ? "vertical" : undefined,
      max_duration: state.short ? 5 : undefined,
      category: state.categories,
      availability: state.availability || undefined,
      analysis: state.analysis || undefined,
      sort: state.sort,
      limit: PAGE,
      offset: state.offset,
      ...fixed,
    }),
    [debounced, state, fixed],
  );
  const list = useAsync(() => api.assets(filters), [filters, refreshKey]);
  const pendingInList = (list.data?.items ?? []).some((a) => a.preview.status === "pending" || a.version.analysis_status !== "done");
  useInterval(() => list.reload(true), 2500, busy || pendingInList);
  const listRef = useRef<HTMLDivElement>(null);

  // Cambiar filtros vuelve a la primera página.
  const set = (patch: Partial<ExploreState>) => onState({ ...state, ...patch, offset: patch.offset ?? 0 });

  const activeFilters = state.alpha || state.vertical || state.short || state.categories.length > 0 || !!state.availability || !!state.analysis || !!query;
  const clear = () => onState({ ...initialExplore, sort: state.sort });
  const total = list.data?.total ?? 0;
  const showFilters = props.showFilters !== false;

  return (
    <>
      <div className="view-head">
        <h1>{props.title}</h1>
        {props.subtitle && <p>{props.subtitle}</p>}
      </div>
      {showFilters && (
        <div className="filters" role="group" aria-label="Filtros">
          <button type="button" className="chip" aria-pressed={!activeFilters} onClick={clear}>Todos</button>
          <button type="button" className="chip" aria-pressed={state.alpha} onClick={() => set({ alpha: !state.alpha })}>Con transparencia</button>
          <button type="button" className="chip" aria-pressed={state.vertical} onClick={() => set({ vertical: !state.vertical })}>Vertical</button>
          <button type="button" className="chip" aria-pressed={state.short} onClick={() => set({ short: !state.short })}>Menos de 5 s</button>
          <button type="button" className="chip chip-icon" aria-pressed={more} aria-expanded={more} aria-label="Más filtros" title="Más filtros" onClick={() => setMore(!more)}><IconSliders /></button>
          <span className="count" aria-live="polite">{list.loading && !list.data ? "Cargando…" : `${total} ${total === 1 ? "recurso" : "recursos"}`}</span>
        </div>
      )}
      {showFilters && more && (
        <div className="more-filters">
          <div>
            <div className="tiny" style={{ marginBottom: 6 }}>Categoría</div>
            <div className="checks">
              {categories.map((c) => (
                <label key={c}>
                  <input
                    type="checkbox"
                    checked={state.categories.includes(c)}
                    onChange={(e) => set({ categories: e.target.checked ? [...state.categories, c] : state.categories.filter((x) => x !== c) })}
                  />
                  {CATEGORY_LABELS[c] ?? c}
                </label>
              ))}
            </div>
          </div>
          <label>Disponibilidad
            <select value={state.availability} onChange={(e) => set({ availability: e.target.value as ExploreState["availability"] })}>
              <option value="">Todas</option>
              <option value="available">Original disponible</option>
              <option value="offline">Original offline</option>
            </select>
          </label>
          <label>Estado del análisis
            <select value={state.analysis} onChange={(e) => set({ analysis: e.target.value as ExploreState["analysis"] })}>
              <option value="">Todos</option>
              <option value="done">Completo</option>
              <option value="pending">Pendiente</option>
              <option value="failed">Fallido</option>
            </select>
          </label>
          <label>Orden
            <select value={state.sort} onChange={(e) => set({ sort: e.target.value as ExploreState["sort"] })}>
              <option value="recent">Más recientes</option>
              <option value="title">Título</option>
              <option value="duration">Duración</option>
              <option value="size">Tamaño</option>
            </select>
          </label>
        </div>
      )}

      {list.error && <div className="notice warn">No se pudo cargar el catálogo: {list.error}</div>}

      {list.data && list.data.items.length === 0 && !list.loading && (
        <div className="empty">
          <h2>Sin resultados</h2>
          <p>{activeFilters ? "Ningún recurso coincide con la búsqueda y los filtros." : props.emptyHint ?? "Todavía no hay recursos en la biblioteca."}</p>
          {activeFilters && <button type="button" className="btn" onClick={clear}>Limpiar filtros</button>}
        </div>
      )}

      <div className="gallery" role="listbox" aria-label="Recursos" ref={listRef}>
        {(list.data?.items ?? []).map((a) => (
          <AssetCard
            key={a.id}
            asset={a}
            selected={a.id === selectedId}
            hovering={hover === a.id}
            reducedMotion={reduced}
            onHover={setHover}
            onOpen={onOpen}
            onToggleFavorite={(asset) => {
              onToggleFavorite(asset).then(() => list.reload(true));
            }}
          />
        ))}
      </div>

      {list.data && total > PAGE && (
        <div className="pager">
          <button type="button" className="btn" disabled={state.offset === 0} onClick={() => onState({ ...state, offset: Math.max(0, state.offset - PAGE) })}>Anterior</button>
          <span className="muted" style={{ alignSelf: "center" }}>{state.offset + 1}–{Math.min(total, state.offset + PAGE)} de {total}</span>
          <button type="button" className="btn" disabled={state.offset + PAGE >= total} onClick={() => onState({ ...state, offset: state.offset + PAGE })}>Siguiente</button>
        </div>
      )}
    </>
  );
}
