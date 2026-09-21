import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type Asset, type AssetFilters, type Pack, CATEGORY_LABELS } from "./api";
import { AssetCard } from "./AssetCard";
import { useDebounced, useInterval, useReducedMotion } from "./hooks";
import { IconSliders } from "./icons";

export interface ExploreState {
  alpha: boolean;
  vertical: boolean;
  short: boolean;
  categories: string[];
  availability: "" | "available" | "offline" | "archived";
  analysis: "" | "pending" | "failed" | "done";
  packId: string;
  mediaKind: "" | "video" | "audio" | "image" | "other";
  duplicates: boolean;
  sort: "recent" | "title" | "duration" | "size";
  offset: number;
}

export const initialExplore: ExploreState = {
  alpha: false, vertical: false, short: false, categories: [], availability: "", analysis: "", packId: "", mediaKind: "", duplicates: false, sort: "recent", offset: 0,
};

interface Props {
  title: string;
  subtitle?: string;
  query: string;
  state: ExploreState;
  onState: (s: ExploreState) => void;
  fixed?: Partial<AssetFilters>;
  categories: string[];
  packs?: Pack[];
  selectedId: string | null;
  onOpen: (asset: Asset, el: HTMLElement) => void;
  onToggleFavorite: (asset: Asset) => Promise<void>;
  busy: boolean;
  refreshKey: number;
  showFilters?: boolean;
  emptyHint?: string;
}

const PAGE = 120;
const GAP_X = 18;
const GAP_Y = 22;
const MIN_CARD = 280;
const TITLE_H = 46;
const OVERSCAN_ROWS = 2;

/**
 * Galería virtualizada: solo se montan las filas visibles (más un margen) y los datos se piden
 * por páginas según se desplaza. Soporta inventarios de miles de recursos sin cargar todos.
 */
export function Explore(props: Props) {
  const { query, state, onState, fixed, selectedId, onOpen, onToggleFavorite, busy, refreshKey, categories, packs } = props;
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
      pack_id: state.packId || undefined,
      media_kind: state.mediaKind || undefined,
      duplicates: state.duplicates || undefined,
      sort: state.sort,
      ...fixed,
    }),
    [debounced, state, fixed],
  );
  const filtersKey = JSON.stringify(filters) + refreshKey;

  // Datos: total + mapa disperso de páginas cargadas.
  const [total, setTotal] = useState<number | null>(null);
  const [items, setItems] = useState<Map<number, Asset>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const loadedPages = useRef<Set<number>>(new Set());
  const inflight = useRef<Set<number>>(new Set());
  const gen = useRef(0);

  const loadPage = useCallback(
    (page: number, force = false) => {
      if (!force && (loadedPages.current.has(page) || inflight.current.has(page))) return;
      const myGen = gen.current;
      inflight.current.add(page);
      api
        .assets({ ...filters, limit: PAGE, offset: page * PAGE })
        .then((res) => {
          if (myGen !== gen.current) return;
          setTotal(res.total);
          setItems((prev) => {
            const next = new Map(prev);
            res.items.forEach((a, i) => next.set(page * PAGE + i, a));
            return next;
          });
          loadedPages.current.add(page);
          setError(null);
        })
        .catch((e: Error) => myGen === gen.current && setError(e.message))
        .finally(() => inflight.current.delete(page));
    },
    [filters],
  );

  // Cambio de filtros → reiniciar datos y volver arriba.
  useEffect(() => {
    gen.current += 1;
    loadedPages.current = new Set();
    inflight.current = new Set();
    setItems(new Map());
    setTotal(null);
    scrollerRef.current?.scrollTo({ top: 0 });
    loadPage(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey]);

  // Refresco silencioso de las páginas cargadas mientras hay trabajo pendiente.
  const pendingVisible = Array.from(items.values()).some((a) => a.preview.status === "pending" || (a.version.analysis_status !== "done" && a.available));
  useInterval(() => {
    for (const p of Array.from(loadedPages.current)) loadPage(p, true);
  }, 3000, busy || pendingVisible);

  // Geometría.
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(800);
  const [gridTop, setGridTop] = useState(0);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const scroller = grid.closest(".content") as HTMLDivElement | null;
    scrollerRef.current = scroller;
    const measure = () => {
      setWidth(grid.clientWidth);
      if (scroller) {
        setViewportH(scroller.clientHeight);
        setGridTop(grid.offsetTop);
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    if (scroller) ro.observe(scroller);
    const onScroll = () => scroller && setScrollTop(scroller.scrollTop);
    scroller?.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      ro.disconnect();
      scroller?.removeEventListener("scroll", onScroll);
    };
  }, [more, props.title]);

  const cols = Math.max(1, Math.floor((width + GAP_X) / (MIN_CARD + GAP_X)));
  const cardW = cols > 0 ? (width - GAP_X * (cols - 1)) / cols : width;
  const rowH = cardW * 9 / 16 + TITLE_H + GAP_Y;
  const count = total ?? 0;
  const rows = Math.ceil(count / cols);
  const relScroll = Math.max(0, scrollTop - gridTop);
  const firstRow = Math.max(0, Math.floor(relScroll / rowH) - OVERSCAN_ROWS);
  const lastRow = Math.min(rows - 1, Math.ceil((relScroll + viewportH) / rowH) + OVERSCAN_ROWS);

  useEffect(() => {
    if (total === null) return;
    const firstIdx = firstRow * cols;
    const lastIdx = Math.min(count - 1, (lastRow + 1) * cols - 1);
    for (let p = Math.floor(firstIdx / PAGE); p <= Math.floor(Math.max(0, lastIdx) / PAGE); p++) loadPage(p);
  }, [firstRow, lastRow, cols, total, count, loadPage]);

  const set = (patch: Partial<ExploreState>) => onState({ ...state, ...patch, offset: 0 });
  const activeFilters = state.alpha || state.vertical || state.short || state.categories.length > 0 || !!state.availability || !!state.analysis || !!state.packId || !!state.mediaKind || state.duplicates || !!query;
  const clear = () => onState({ ...initialExplore, sort: state.sort });
  const showFilters = props.showFilters !== false;

  const visible: { idx: number; asset: Asset | undefined }[] = [];
  if (total !== null) {
    for (let r = firstRow; r <= lastRow; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        if (idx < count) visible.push({ idx, asset: items.get(idx) });
      }
    }
  }

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
          <button type="button" className="chip" aria-pressed={state.availability === "available"} onClick={() => set({ availability: state.availability === "available" ? "" : "available" })}>Listos</button>
          <button type="button" className="chip chip-icon" aria-pressed={more} aria-expanded={more} aria-label="Más filtros" title="Más filtros" onClick={() => setMore(!more)}><IconSliders /></button>
          <span className="count" aria-live="polite">{total === null ? "Cargando…" : `${total} ${total === 1 ? "recurso" : "recursos"}`}</span>
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
              <option value="archived">En pack, sin extraer</option>
              <option value="offline">Original offline</option>
            </select>
          </label>
          <label>Tipo
            <select value={state.mediaKind} onChange={(e) => set({ mediaKind: e.target.value as ExploreState["mediaKind"] })}>
              <option value="">Todos</option>
              <option value="video">Vídeo</option>
              <option value="audio">Audio</option>
              <option value="image">Imagen</option>
              <option value="other">Plantillas, LUT y otros</option>
            </select>
          </label>
          {packs && packs.length > 0 && (
            <label>Pack
              <select value={state.packId} onChange={(e) => set({ packId: e.target.value })}>
                <option value="">Todos</option>
                {packs.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </label>
          )}
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
          <label className="checks" style={{ alignSelf: "end" }}>
            <span><input type="checkbox" checked={state.duplicates} onChange={(e) => set({ duplicates: e.target.checked })} /> Solo duplicados y candidatos</span>
          </label>
        </div>
      )}

      {error && <div className="notice warn">No se pudo cargar el catálogo: {error}</div>}

      {total === 0 && (
        <div className="empty">
          <h2>Sin resultados</h2>
          <p>{activeFilters ? "Ningún recurso coincide con la búsqueda y los filtros." : props.emptyHint ?? "Todavía no hay recursos en la biblioteca."}</p>
          {activeFilters && <button type="button" className="btn" onClick={clear}>Limpiar filtros</button>}
        </div>
      )}

      <div ref={gridRef} className="vgrid" role="listbox" aria-label="Recursos" aria-rowcount={rows} style={{ height: total ? rows * rowH - GAP_Y : 0 }}>
        {visible.map(({ idx, asset }) => {
          const r = Math.floor(idx / cols);
          const c = idx % cols;
          const style = { position: "absolute" as const, top: r * rowH, left: c * (cardW + GAP_X), width: cardW };
          if (!asset) return <div key={idx} className="card-skeleton" style={{ ...style, height: rowH - GAP_Y }} aria-hidden="true" />;
          return (
            <div key={asset.id} style={style}>
              <AssetCard
                asset={asset}
                selected={asset.id === selectedId}
                hovering={hover === asset.id}
                reducedMotion={reduced}
                onHover={setHover}
                onOpen={onOpen}
                onToggleFavorite={(a) => {
                  onToggleFavorite(a).then(() => loadPage(Math.floor(idx / PAGE), true));
                }}
              />
            </div>
          );
        })}
      </div>
    </>
  );
}
