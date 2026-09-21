import { useState } from "react";
import { api, type Asset, type Named } from "./api";
import { Explore, type ExploreState, initialExplore } from "./Explore";
import { useAsync } from "./hooks";
import { IconFolder } from "./icons";

interface ListProps {
  onOpen: (id: string) => void;
  refreshKey: number;
}

export function CollectionsList({ onOpen, refreshKey }: ListProps) {
  const list = useAsync(() => api.collections(), [refreshKey]);
  const [name, setName] = useState("");
  const covers = useAsync(async () => {
    const out: Record<string, string> = {};
    for (const c of list.data ?? []) if (c.cover_asset_id) out[c.id] = `/api/assets/${c.cover_asset_id}/thumb`;
    return out;
  }, [list.data]);
  return (
    <>
      <div className="view-head"><h1>Colecciones</h1><p>Agrupaciones editables. Un recurso puede estar en varias.</p></div>
      <form className="create-row" onSubmit={async (e) => { e.preventDefault(); if (!name.trim()) return; await api.createCollection(name.trim()); setName(""); list.reload(); }}>
        <input className="input" placeholder="Nueva colección…" aria-label="Nombre de la nueva colección" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn primary" disabled={!name.trim()}>Crear</button>
      </form>
      {list.error && <div className="notice warn">{list.error}</div>}
      {list.data && list.data.length === 0 && <div className="empty"><h2>Sin colecciones</h2><p>Crea una y añade recursos desde la ficha (menú ···).</p></div>}
      <div className="cards">
        {(list.data ?? []).map((c) => (
          <button type="button" key={c.id} className="list-card" onClick={() => onOpen(c.id)}>
            <div className="cover">{covers.data?.[c.id] ? <img src={covers.data[c.id]} alt="" /> : <div className="placeholder" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-3)" }}><IconFolder /></div>}</div>
            <h3>{c.name}</h3>
            <span className="tiny">{c.count ?? 0} {c.count === 1 ? "recurso" : "recursos"}{c.description ? ` · ${c.description}` : ""}</span>
          </button>
        ))}
      </div>
    </>
  );
}

interface DetailProps {
  id: string;
  query: string;
  categories: string[];
  selectedId: string | null;
  onOpenAsset: (a: Asset, el: HTMLElement) => void;
  onToggleFavorite: (a: Asset) => Promise<void>;
  onBack: () => void;
  onChanged: () => void;
  busy: boolean;
  refreshKey: number;
}

export function CollectionDetail(props: DetailProps) {
  const col = useAsync(() => api.collection(props.id), [props.id, props.refreshKey]);
  const [state, setState] = useState<ExploreState>(initialExplore);
  const [editing, setEditing] = useState<string | null>(null);
  const fixed = { collection_id: props.id };
  if (col.error) return <div className="notice warn">{col.error}</div>;
  const c: Named | null = col.data;
  return (
    <>
      <div className="detail-head">
        <button type="button" className="btn ghost small" onClick={props.onBack}>← Colecciones</button>
        <h1>
          <input aria-label="Nombre de la colección" value={editing ?? c?.name ?? ""} onChange={(e) => setEditing(e.target.value)}
            onBlur={async () => { if (editing && c && editing.trim() && editing !== c.name) { await api.patchCollection(c.id, { name: editing.trim() }); props.onChanged(); } setEditing(null); }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        </h1>
        <button type="button" className="btn ghost small danger" onClick={async () => { if (c && window.confirm(`¿Eliminar la colección «${c.name}»? Los recursos y sus originales no se borran.`)) { await api.deleteCollection(c.id); props.onChanged(); props.onBack(); } }}>Eliminar colección</button>
      </div>
      <Explore
        title=""
        query={props.query}
        state={state}
        onState={setState}
        fixed={fixed}
        categories={props.categories}
        selectedId={props.selectedId}
        onOpen={props.onOpenAsset}
        onToggleFavorite={props.onToggleFavorite}
        busy={props.busy}
        refreshKey={props.refreshKey}
        showFilters
        emptyHint="Esta colección está vacía. Añade recursos desde la ficha (menú ···)."
      />
    </>
  );
}
