import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Asset, type Config, type Named, type Pack, type Stats, CATEGORY_LABELS } from "./api";
import { CollectionDetail, CollectionsList } from "./Collections";
import { Explore, type ExploreState, initialExplore } from "./Explore";
import { useInterval } from "./hooks";
import { IconMenu, IconSearch } from "./icons";
import { ImportView, PackDetail } from "./Import";
import { Inspector } from "./Inspector";
import { SelectionDetail, SelectionsList } from "./Selections";
import { Sidebar, type View } from "./Sidebar";

function readHash(): View {
  const h = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const [name, id] = h.split("/");
  if (name === "collections" || name === "selections" || name === "favorites" || name === "import") return { name, id: id || undefined };
  if (name === "category" && id) return { name: "explore", category: id };
  return { name: "explore" };
}

/** `#/...?asset=<id>` abre la ficha de ese recurso (enlace compartible dentro de la sesión). */
function readAssetFromHash(): string | null {
  const q = window.location.hash.split("?")[1];
  return q ? new URLSearchParams(q).get("asset") : null;
}

function writeHash(v: View, assetId: string | null) {
  const base = v.name === "explore" ? (v.category ? `#/category/${v.category}` : "#/") : `#/${v.name}${v.id ? `/${v.id}` : ""}`;
  const h = assetId ? `${base}?asset=${assetId}` : base;
  if (window.location.hash !== h) window.history.replaceState(null, "", h);
}

export default function App() {
  const [view, setViewState] = useState<View>(readHash);
  const [query, setQuery] = useState("");
  const [explore, setExplore] = useState<ExploreState>(initialExplore);
  const [selectedId, setSelectedId] = useState<string | null>(readAssetFromHash);
  const [config, setConfig] = useState<Config | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selections, setSelections] = useState<Named[]>([]);
  const [collections, setCollections] = useState<Named[]>([]);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
  const lastFocus = useRef<HTMLElement | null>(null);

  const setView = useCallback((v: View) => {
    setViewState(v);
    setNavOpen(false);
    if (v.name !== view.name || v.id !== view.id) setSelectedId(null);
    if (v.name === "explore" && v.category !== view.category) setExplore((s) => ({ ...s, offset: 0 }));
  }, [view.category, view.name, view.id]);

  useEffect(() => { writeHash(view, selectedId); }, [view, selectedId]);

  useEffect(() => {
    const on = () => { setViewState(readHash()); setSelectedId(readAssetFromHash()); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const refreshMeta = useCallback(() => {
    api.stats().then(setStats).catch(() => undefined);
    api.selections().then(setSelections).catch(() => undefined);
    api.collections().then(setCollections).catch(() => undefined);
    api.packs().then(setPacks).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
    refreshMeta();
  }, [refreshMeta]);

  const pollJobs = useCallback(() => {
    api.jobsSummary().then((s) => {
      const running = s.totals.running ?? 0;
      const queued = s.totals.queued ?? 0;
      const active = running + queued > 0;
      setBusy(active);
      setBusyLabel(active ? `${running + queued} ${running + queued === 1 ? "trabajo" : "trabajos"} en curso` : "");
      if (active) refreshMeta();
    }).catch(() => undefined);
  }, [refreshMeta]);
  useEffect(pollJobs, [pollJobs]);
  useInterval(pollJobs, busy ? 2000 : 8000, true);
  useEffect(() => { if (!busy) refreshMeta(); }, [busy, refreshMeta]);

  const openAsset = useCallback((asset: Asset, el: HTMLElement) => {
    lastFocus.current = el;
    setSelectedId(asset.id);
  }, []);
  const closeInspector = useCallback(() => {
    setSelectedId(null);
    lastFocus.current?.focus();
  }, []);
  const toggleFavorite = useCallback(async (asset: Asset) => {
    await api.patchAsset(asset.id, { favorite: !asset.favorite });
    refreshMeta();
  }, [refreshMeta]);
  const bump = () => { setRefreshKey((k) => k + 1); refreshMeta(); };

  const categories = config?.categories ?? Object.keys(CATEGORY_LABELS);
  const exploreProps = {
    query, categories, packs, selectedId, onOpen: openAsset, onToggleFavorite: toggleFavorite, busy, refreshKey,
  };
  const openAssetById = (id: string) => setSelectedId(id);

  let body: JSX.Element;
  switch (view.name) {
    case "collections":
      body = view.id
        ? <CollectionDetail id={view.id} query={query} categories={categories} selectedId={selectedId} onOpenAsset={openAsset} onToggleFavorite={toggleFavorite} busy={busy} refreshKey={refreshKey} onBack={() => setView({ name: "collections" })} onChanged={bump} />
        : <CollectionsList onOpen={(id) => setView({ name: "collections", id })} refreshKey={refreshKey} />;
      break;
    case "selections":
      body = view.id
        ? <SelectionDetail id={view.id} selectedId={selectedId} onOpenAsset={openAsset} onBack={() => setView({ name: "selections" })} onChanged={bump} refreshKey={refreshKey} />
        : <SelectionsList onOpen={(id) => setView({ name: "selections", id })} refreshKey={refreshKey} />;
      break;
    case "favorites":
      body = <Explore title="Favoritos" subtitle="Lo que has marcado con el corazón." state={explore} onState={setExplore} fixed={{ favorite: true }} {...exploreProps} emptyHint="Todavía no hay favoritos." />;
      break;
    case "import":
      body = view.id
        ? <PackDetail id={view.id} onBack={() => setView({ name: "import" })} onExplore={(packId) => { setExplore({ ...initialExplore, packId }); setView({ name: "explore" }); }} />
        : <ImportView config={config} busy={busy} onImported={() => { pollJobs(); bump(); }} onOpenPack={(id) => setView({ name: "import", id })} />;
      break;
    default:
      body = (
        <Explore
          title={view.category ? CATEGORY_LABELS[view.category] ?? view.category : "Explora tu biblioteca"}
          subtitle={view.category ? undefined : "Encuentra el recurso. Imagina la escena."}
          state={explore}
          onState={setExplore}
          fixed={view.category ? { category: [view.category] } : undefined}
          {...exploreProps}
          emptyHint="Todavía no hay recursos. Empieza por «Incorporar» en la barra lateral."
        />
      );
  }

  return (
    <div className={`shell${selectedId ? " with-inspector" : ""}`}>
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}
      <Sidebar view={view} stats={stats} categories={categories} open={navOpen} onNavigate={setView} />
      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn menu-toggle" aria-label="Abrir navegación" onClick={() => setNavOpen(true)}><IconMenu /></button>
          <label className="search">
            <IconSearch />
            <span className="sr-only">Buscar recursos</span>
            <input type="search" placeholder="¿Qué necesitas para tu próxima pieza?" value={query} onChange={(e) => { setQuery(e.target.value); setExplore((s) => ({ ...s, offset: 0 })); }} />
          </label>
          {busy && <div className="status-pill" role="status"><span className="dot" />{busyLabel}</div>}
          {stats && stats.archived > 0 && !busy && (
            <button type="button" className="status-pill" title="Recursos catalogados dentro de packs, pendientes de extraer" onClick={() => { setExplore({ ...initialExplore, availability: "archived" }); setView({ name: "explore" }); }}>{stats.archived} sin extraer</button>
          )}
          {stats && stats.analysis_failed > 0 && !busy && (
            <button type="button" className="status-pill" onClick={() => setView({ name: "import" })}>{stats.analysis_failed} con error de análisis</button>
          )}
        </header>
        <main className="content" id="main">{body}</main>
      </div>
      {selectedId && (
        <>
          <div className="scrim" onClick={closeInspector} style={{ display: "none" }} />
          <Inspector
            assetId={selectedId}
            selections={selections}
            collections={collections}
            categories={categories}
            onClose={closeInspector}
            onChanged={() => bump()}
            onSelectionsChanged={refreshMeta}
            onOpenSelection={(id) => setView({ name: "selections", id })}
            onOpenAsset={openAssetById}
          />
        </>
      )}
    </div>
  );
}
