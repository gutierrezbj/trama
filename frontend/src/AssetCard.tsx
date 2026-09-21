import { memo, useEffect, useRef, useState } from "react";
import { type Asset, CATEGORY_LABELS, EXT_LABELS, formatDuration, previewUrl } from "./api";
import { IconAudio, IconBox, IconClock, IconHeart, IconTemplate, IconWarn } from "./icons";

interface Props {
  asset: Asset;
  selected: boolean;
  hovering: boolean;
  reducedMotion: boolean;
  onHover: (id: string | null) => void;
  onOpen: (asset: Asset, el: HTMLElement) => void;
  onToggleFavorite: (asset: Asset) => void;
}

function AssetCardInner({ asset, selected, hovering, reducedMotion, onHover, onOpen, onToggleFavorite }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  const s = asset.summary;
  const isAlpha = asset.preview.kind === "video_alpha";
  const canHoverPlay = !reducedMotion && !videoFailed && asset.preview.status === "ready" && (asset.preview.kind === "video" || isAlpha);
  const showVideo = hovering && canHoverPlay;

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (showVideo) {
      v.currentTime = 0;
      v.play().catch(() => setVideoFailed(true));
    } else {
      v.pause();
    }
  }, [showVideo]);

  const ext = asset.version.ext.replace(".", "").toUpperCase();
  const category = CATEGORY_LABELS[asset.category] ?? asset.category;
  const isOther = asset.version.media_kind === "other";
  const durationLabel =
    s.duration_s !== null ? formatDuration(s.duration_s) : asset.version.analysis_status === "failed" ? "error" : asset.archived ? "sin extraer" : "…";

  let media: JSX.Element;
  if (asset.preview.kind === "audio" && asset.waveform_url) {
    media = <div className="waveform"><img src={asset.waveform_url} alt="" loading="lazy" /></div>;
  } else if (asset.thumb_url) {
    media = (
      <>
        <img src={asset.thumb_url} alt="" loading="lazy" className={isAlpha ? "checker" : undefined} />
        {canHoverPlay && (
          <video
            ref={videoRef}
            src={previewUrl(asset, "checker")}
            muted
            loop
            playsInline
            preload="none"
            aria-hidden="true"
            onError={() => setVideoFailed(true)}
            style={{ position: "absolute", inset: 0, opacity: showVideo ? 1 : 0, pointerEvents: "none" }}
          />
        )}
      </>
    );
  } else if (asset.lut_demo_url) {
    media = (
      <>
        <img src={asset.lut_demo_url} alt="" loading="lazy" />
        <span className="badge demo">Demostración</span>
      </>
    );
  } else if (isOther && asset.provider_preview?.thumb_url) {
    media = (
      <>
        <img src={asset.provider_preview.thumb_url} alt="" loading="lazy" />
        <span className="badge demo">Preview del proveedor</span>
      </>
    );
  } else if (asset.archived) {
    media = (
      <div className="placeholder archived">
        <IconBox />
        En el pack, sin extraer
        {asset.locations[0]?.pack_label && <small>{asset.locations[0].pack_label}</small>}
      </div>
    );
  } else if (asset.version.analysis_status === "failed" || asset.preview.status === "failed") {
    media = <div className="placeholder failed"><IconWarn />Análisis o preview fallido</div>;
  } else if (isOther) {
    media = (
      <div className="placeholder">
        {asset.version.media_kind === "other" ? <IconTemplate /> : <IconBox />}
        {EXT_LABELS[asset.version.ext] ?? `Archivo ${ext}`}
        <small>Sin preview genérica</small>
      </div>
    );
  } else if (asset.preview.kind === "audio") {
    media = <div className="placeholder"><IconAudio />Forma de onda pendiente</div>;
  } else if (!asset.available) {
    media = <div className="placeholder failed"><IconWarn />Original offline</div>;
  } else {
    media = <div className="placeholder"><IconClock />Preview pendiente</div>;
  }

  return (
    <div
      className="card"
      role="option"
      aria-selected={selected}
      onMouseEnter={() => onHover(asset.id)}
      onMouseLeave={() => onHover(null)}
    >
      <button
        ref={ref}
        type="button"
        className="card-media"
        style={{ display: "block", width: "100%", padding: 0, cursor: "pointer" }}
        aria-label={`${asset.title}, ${category}, ${durationLabel}`}
        onClick={() => onOpen(asset, ref.current!)}
        onFocus={() => onHover(asset.id)}
        onBlur={() => onHover(null)}
      >
        {media}
        {!asset.available && !asset.archived && <span className="badge offline">Original offline</span>}
        {asset.duplicate_of && <span className="badge offline" style={{ color: "var(--text-2)" }}>Duplicado</span>}
        {asset.version.media_kind !== "image" && !isOther ? <span className="badge left">{durationLabel}</span> : null}
        <span className="badge right">{category} · {ext}</span>
      </button>
      <button
        type="button"
        className="fav"
        aria-pressed={asset.favorite}
        aria-label={asset.favorite ? "Quitar de favoritos" : "Añadir a favoritos"}
        onClick={(e) => {
          e.stopPropagation();
          onToggleFavorite(asset);
        }}
      >
        <IconHeart filled={asset.favorite} />
      </button>
      <div className="card-title">
        <span title={asset.original_title}>{asset.title}</span>
        {isAlpha && <small title="Transparencia medida">α</small>}
        {asset.version.identity_kind === "provisional" && <small title="Identidad provisional: sin extraer ni verificar por hash">prov.</small>}
      </div>
    </div>
  );
}

export const AssetCard = memo(AssetCardInner);
