import { CATEGORY_LABELS, type Stats } from "./api";
import { CATEGORY_ICONS, IconCloud, IconFolder, IconHeart, IconPlus, IconSearch, IconSelection } from "./icons";

export type ViewName = "explore" | "collections" | "selections" | "favorites" | "import" | "copias";
export interface View {
  name: ViewName;
  id?: string;
  category?: string;
}

interface Props {
  view: View;
  stats: Stats | null;
  categories: string[];
  open: boolean;
  onNavigate: (v: View) => void;
}

export function Sidebar({ view, stats, categories, open, onNavigate }: Props) {
  const is = (name: ViewName, category?: string) => (view.name === name && (category === undefined || view.category === category) && (category !== undefined || !view.category) ? "page" : undefined);
  return (
    <nav className={`sidebar${open ? " open" : ""}`} aria-label="Navegación principal">
      <div className="brand">
        <img className="brand-mark" src="/logo.png" alt="" aria-hidden="true" />
        <div>
          <span className="brand-name">TRAMA</span>
          <span className="brand-sub">Un producto de JRGB</span>
        </div>
      </div>
      <button type="button" className="nav-item" aria-current={is("explore")} onClick={() => onNavigate({ name: "explore" })}><IconSearch />Explorar</button>
      <button type="button" className="nav-item" aria-current={view.name === "collections" ? "page" : undefined} onClick={() => onNavigate({ name: "collections" })}><IconFolder />Colecciones</button>
      <button type="button" className="nav-item" aria-current={view.name === "selections" ? "page" : undefined} onClick={() => onNavigate({ name: "selections" })}><IconSelection />Mis selecciones</button>
      <button type="button" className="nav-item" aria-current={is("favorites")} onClick={() => onNavigate({ name: "favorites" })}><IconHeart />Favoritos{stats && stats.favorites > 0 && <span className="count">{stats.favorites}</span>}</button>

      <div className="nav-section">Recursos</div>
      {categories.map((c) => {
        const Icon = CATEGORY_ICONS[c] ?? CATEGORY_ICONS.otros;
        const n = stats?.categories[c] ?? 0;
        if (n === 0 && ["imagenes", "documentacion", "otros", "plantillas", "fondos"].includes(c)) return null;
        return (
          <button type="button" key={c} className="nav-item" aria-current={is("explore", c)} onClick={() => onNavigate({ name: "explore", category: c })}>
            <Icon />{CATEGORY_LABELS[c] ?? c}
            {n > 0 && <span className="count">{n}</span>}
          </button>
        );
      })}

      <div className="sidebar-bottom">
        <button type="button" className="nav-item" aria-current={view.name === "copias" ? "page" : undefined} onClick={() => onNavigate({ name: "copias" })}><IconCloud />Copias y Drive</button>
        <button type="button" className="btn-import" aria-current={view.name === "import" ? "page" : undefined} onClick={() => onNavigate({ name: "import" })}><IconPlus />Incorporar</button>
      </div>
    </nav>
  );
}
