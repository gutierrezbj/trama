// Cliente de la API de TRAMA. Todos los archivos se resuelven por ID en el backend.

export type MediaKind = "video" | "audio" | "image" | "other";
export type PreviewKind = "video" | "video_alpha" | "audio" | "image" | "lut_demo" | "none";
export type PreviewStatus = "pending" | "ready" | "failed" | "unsupported" | "archived";
export type Bg = "dark" | "light" | "checker";

export interface Summary {
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  frames: number | null;
  rotation: number | null;
  orientation: "horizontal" | "vertical" | "square" | null;
  alpha_format: boolean | null;
  alpha_used: boolean | null;
  codec: string | null;
  pix_fmt: string | null;
  container: string | null;
  has_audio: boolean;
  sample_rate: number | null;
  channels: number | null;
  bits: number | null;
  media_kind: MediaKind;
}

export interface Location {
  id: string;
  source_id: string;
  source_label: string;
  rel_path: string;
  file_name: string;
  status: "available" | "offline" | "archived";
  size: number;
  last_seen_at: string;
  kind: "local" | "pack";
  pack_id?: string | null;
  pack_label?: string | null;
  inner_path?: string | null;
  entry_status?: string | null;
  entry_error?: string | null;
  unsafe_reason?: string | null;
}

export interface Pack {
  id: string;
  source_id: string;
  rel_path: string;
  label: string;
  size: number;
  status: "pending" | "indexing" | "indexed" | "failed" | "offline";
  entries_total: number;
  entries_media: number;
  entries_unsafe: number;
  bytes_total: number;
  error: string | null;
  indexed_at: string | null;
  extracted: number;
  extracted_bytes: number;
  failed: number;
  active_job: { id: string; kind: string; status: string; progress: number; message: string | null } | null;
  zip_present: boolean;
  folders?: PackFolder[];
  unsafe_entries?: { inner_path: string; unsafe_reason: string }[];
  failed_entries?: { id: string; inner_path: string; error: string }[];
}

export interface PackFolder {
  path: string;
  depth: number;
  entries: number;
  media: number;
  extracted: number;
  bytes: number;
  extracted_bytes: number;
  unsafe: number;
}

export interface Storage {
  data_dir: string;
  cache_bytes: number;
  cache_max_bytes: number;
  derivatives_bytes: number;
  disk_free_bytes: number;
  disk_total_bytes: number;
  min_free_bytes: number;
}

export interface Asset {
  id: string;
  title: string;
  original_title: string;
  category: string;
  category_source: "inferred" | "human";
  description: string;
  description_source: "none" | "human" | "inferred";
  tags: string[];
  favorite: boolean;
  created_at: string;
  updated_at: string;
  version: {
    id: string;
    sha256: string;
    identity_kind: "sha256" | "provisional";
    size: number;
    ext: string;
    media_kind: MediaKind;
    analysis_status: "pending" | "running" | "done" | "failed";
    analysis_error: string | null;
    analyzed_at: string | null;
  };
  summary: Summary;
  available: boolean;
  archived: boolean;
  extractable: boolean;
  duplicate_of: string | null;
  required_app: string | null;
  provider_preview: { asset_id: string; title: string; thumb_url: string | null } | null;
  lut: { title: string | null; size_3d: number | null; size_1d: number | null } | null;
  lut_demo_url: string | null;
  locations: Location[];
  derivatives: Record<string, { status: string; error: string | null; width: number | null; height: number | null }>;
  preview: { kind: PreviewKind; status: PreviewStatus; backgrounds: Bg[] };
  thumb_url: string | null;
  waveform_url: string | null;
  in_selections: string[];
  in_collections: string[];
  analysis?: unknown;
  jobs?: Job[];
  item_note?: string;
}

export interface AssetList {
  items: Asset[];
  total: number;
  limit: number;
  offset: number;
}

export interface Named {
  id: string;
  name: string;
  description?: string;
  notes?: string;
  count?: number;
  cover_asset_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  kind: "import" | "analyze" | "derive";
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  attempts: number;
  progress: number;
  message: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  asset_id?: string | null;
  asset_title?: string | null;
  import_id?: string | null;
}

export interface JobsSummary {
  by_status: Record<string, Record<string, number>>;
  totals: Record<string, number>;
}

export interface Import {
  id: string;
  source_id: string;
  sub_path: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  total_files: number;
  processed: number;
  added: number;
  updated: number;
  unchanged: number;
  offline: number;
  errors: { path: string; error: string }[];
  message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Source {
  id: string;
  label: string;
  path: string;
  exists: boolean;
  locations: number;
}

export interface Browse {
  source_id: string;
  path: string;
  parent: string | null;
  dirs: { name: string; path: string; media_files: number; zip_files: number }[];
  zips: { name: string; path: string; size: number; pack_id: string | null; pack_status: string | null; entries_media: number | null }[];
  media_files: number;
}

export interface Config {
  version: string;
  data_dir: string;
  categories: string[];
  tools: { ok: boolean; ffmpeg?: string; ffprobe?: string; error?: string };
  sources: Source[];
}

export interface Stats {
  total: number;
  favorites: number;
  categories: Record<string, number>;
  analysis_pending: number;
  analysis_failed: number;
  archived: number;
  packs: number;
}

export interface AssetFilters {
  q?: string;
  category?: string[];
  alpha?: boolean;
  orientation?: string;
  max_duration?: number;
  min_duration?: number;
  availability?: "available" | "offline" | "archived";
  favorite?: boolean;
  analysis?: string;
  collection_id?: string;
  selection_id?: string;
  pack_id?: string;
  media_kind?: string;
  duplicates?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* sin cuerpo */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const qs = (params: Record<string, unknown>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    sp.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  config: () => request<Config>("/api/config"),
  stats: () => request<Stats>("/api/stats"),
  tags: () => request<{ tag: string; count: number }[]>("/api/tags"),
  assets: (f: AssetFilters) => request<AssetList>(`/api/assets${qs(f as Record<string, unknown>)}`),
  asset: (id: string) => request<Asset>(`/api/assets/${id}`),
  patchAsset: (id: string, body: Partial<Pick<Asset, "title" | "description" | "tags" | "category" | "favorite">>) =>
    request<Asset>(`/api/assets/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  reanalyze: (id: string) => request<Asset>(`/api/assets/${id}/reanalyze`, { method: "POST" }),
  extractAsset: (id: string) => request<{ job_id: string | null; message?: string }>(`/api/assets/${id}/extract`, { method: "POST" }),
  releaseAsset: (id: string) => request<{ released: number }>(`/api/assets/${id}/release`, { method: "POST" }),

  packs: () => request<Pack[]>("/api/packs"),
  pack: (id: string) => request<Pack>(`/api/packs/${id}`),
  indexPacks: (sourceId: string, path: string) =>
    request<{ packs: { pack_id: string; label: string; job_id: string }[] }>("/api/packs/index", { method: "POST", body: JSON.stringify({ source_id: sourceId, path }) }),
  reindexPack: (id: string) => request<{ job_id: string }>(`/api/packs/${id}/reindex`, { method: "POST" }),
  patchPack: (id: string, label: string) => request<Pack>(`/api/packs/${id}`, { method: "PATCH", body: JSON.stringify({ label }) }),
  extractPack: (id: string, prefix = "", entryIds: string[] = []) =>
    request<{ job_id: string | null; entries: number; bytes: number; message?: string }>(`/api/packs/${id}/extract`, { method: "POST", body: JSON.stringify({ prefix, entry_ids: entryIds }) }),
  releasePack: (id: string, prefix = "", entryIds: string[] = []) =>
    request<{ released: number }>(`/api/packs/${id}/release`, { method: "POST", body: JSON.stringify({ prefix, entry_ids: entryIds }) }),
  storage: () => request<Storage>("/api/storage"),

  collections: () => request<Named[]>("/api/collections"),
  collection: (id: string) => request<Named & { assets: Asset[] }>(`/api/collections/${id}`),
  createCollection: (name: string, description = "") =>
    request<Named>("/api/collections", { method: "POST", body: JSON.stringify({ name, description }) }),
  patchCollection: (id: string, body: { name?: string; description?: string }) =>
    request<Named>(`/api/collections/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCollection: (id: string) => request<void>(`/api/collections/${id}`, { method: "DELETE" }),
  addToCollection: (id: string, assetId: string) => request<void>(`/api/collections/${id}/assets/${assetId}`, { method: "PUT" }),
  removeFromCollection: (id: string, assetId: string) =>
    request<void>(`/api/collections/${id}/assets/${assetId}`, { method: "DELETE" }),

  selections: () => request<Named[]>("/api/selections"),
  selection: (id: string) => request<Named & { items: Asset[] }>(`/api/selections/${id}`),
  createSelection: (name: string, notes = "") =>
    request<Named>("/api/selections", { method: "POST", body: JSON.stringify({ name, notes }) }),
  patchSelection: (id: string, body: { name?: string; notes?: string }) =>
    request<Named>(`/api/selections/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSelection: (id: string) => request<void>(`/api/selections/${id}`, { method: "DELETE" }),
  addToSelection: (id: string, assetId: string) => request<void>(`/api/selections/${id}/items/${assetId}`, { method: "PUT" }),
  removeFromSelection: (id: string, assetId: string) =>
    request<void>(`/api/selections/${id}/items/${assetId}`, { method: "DELETE" }),
  patchSelectionItem: (id: string, assetId: string, note: string) =>
    request<void>(`/api/selections/${id}/items/${assetId}`, { method: "PATCH", body: JSON.stringify({ note }) }),
  orderSelection: (id: string, assetIds: string[]) =>
    request<void>(`/api/selections/${id}/order`, { method: "PUT", body: JSON.stringify({ asset_ids: assetIds }) }),

  sources: () => request<Source[]>("/api/fs/sources"),
  browse: (sourceId: string, path: string) => request<Browse>(`/api/fs/browse${qs({ source_id: sourceId, path })}`),
  imports: () => request<Import[]>("/api/imports"),
  createImport: (sourceId: string, path: string) =>
    request<Import>("/api/imports", { method: "POST", body: JSON.stringify({ source_id: sourceId, path }) }),
  cancelImport: (id: string) => request<void>(`/api/imports/${id}/cancel`, { method: "POST" }),
  jobs: (status?: string) => request<Job[]>(`/api/jobs${qs({ status, limit: 200 })}`),
  jobsSummary: () => request<JobsSummary>("/api/jobs/summary"),
  retryJob: (id: string) => request<void>(`/api/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) => request<void>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  retryFailed: () => request<{ retried: number }>("/api/jobs/retry-failed", { method: "POST" }),
};

export const previewUrl = (asset: Asset, bg: Bg = "dark") =>
  `/api/assets/${asset.id}/preview${asset.preview.kind === "video_alpha" ? `?bg=${bg}` : ""}`;
export const originalUrl = (asset: Asset, inline = false) => `/api/assets/${asset.id}/original${inline ? "?inline=1" : ""}`;

export const CATEGORY_LABELS: Record<string, string> = {
  vfx: "VFX",
  overlays: "Overlays",
  transiciones: "Transiciones",
  animacion: "Animación",
  fondos: "Fondos",
  imagenes: "Imágenes",
  color: "Color",
  plantillas: "Plantillas",
  audio: "Audio de producción",
  documentacion: "Documentación",
  otros: "Otros",
};

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return `${m}:${String(s).padStart(2, "0")} min`;
}

export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds - m * 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export const EXT_LABELS: Record<string, string> = {
  ".mogrt": "Plantilla MOGRT",
  ".aep": "Proyecto After Effects",
  ".prproj": "Proyecto Premiere",
  ".drp": "Proyecto Resolve",
  ".drfx": "Plantilla Fusion",
  ".look": "Look",
  ".cube": "LUT 3D",
  ".3dl": "LUT 3D",
  ".psd": "Photoshop",
  ".exr": "Imagen EXR",
  ".pdf": "Documento PDF",
};

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes && bytes !== 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
