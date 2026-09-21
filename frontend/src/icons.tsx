import type { SVGProps } from "react";

const base = (props: SVGProps<SVGSVGElement>) => ({
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  ...props,
});

export const IconSearch = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const IconFolder = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" /></svg>
);
export const IconSelection = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 3v4M17 3v4M3 11h18" /></svg>
);
export const IconHeart = (p: SVGProps<SVGSVGElement> & { filled?: boolean }) => {
  const { filled, ...rest } = p;
  return (
    <svg {...base(rest)} fill={filled ? "currentColor" : "none"}>
      <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" />
    </svg>
  );
};
export const IconSparkle = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" /></svg>
);
export const IconLayers = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="m12 4 8 4-8 4-8-4 8-4Z" /><path d="m4 12 8 4 8-4M4 16l8 4 8-4" /></svg>
);
export const IconPlay = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} fill="currentColor" stroke="none"><path d="M7 5v14l11-7L7 5Z" /></svg>
);
export const IconPause = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} fill="currentColor" stroke="none"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
);
export const IconAnim = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 1 8 8h-8Z" fill="currentColor" stroke="none" opacity="0.5" /></svg>
);
export const IconColor = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><circle cx="9" cy="10" r="5" /><circle cx="15" cy="10" r="5" /><circle cx="12" cy="15" r="5" /></svg>
);
export const IconAudio = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 12v2M8 8v8M12 5v14M16 9v6M20 11v2" /></svg>
);
export const IconImage = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="10" r="1.5" /><path d="m21 16-5-5-8 8" /></svg>
);
export const IconTemplate = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 10v10" /></svg>
);
export const IconDoc = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></svg>
);
export const IconBox = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="M4 7.5 12 12l8-4.5M12 12v9" /></svg>
);
export const IconPlus = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>
);
export const IconMore = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)} fill="currentColor" stroke="none"><circle cx="6" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="18" cy="12" r="1.6" /></svg>
);
export const IconClose = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
export const IconSliders = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 7h10M18 7h2M4 17h4M12 17h8M4 12h16" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>
);
export const IconExternal = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M14 4h6v6M20 4l-9 9" /><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></svg>
);
export const IconDownload = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M12 4v11M7 10l5 5 5-5M4 19h16" /></svg>
);
export const IconMenu = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);
export const IconRefresh = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v5h-5" /></svg>
);
export const IconUp = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="m6 14 6-6 6 6" /></svg>;
export const IconDown = (p: SVGProps<SVGSVGElement>) => <svg {...base(p)}><path d="m6 10 6 6 6-6" /></svg>;
export const IconWarn = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><path d="M12 4 3 19h18L12 4Z" /><path d="M12 10v4M12 17h.01" /></svg>
);
export const IconClock = (p: SVGProps<SVGSVGElement>) => (
  <svg {...base(p)}><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>
);

export const CATEGORY_ICONS: Record<string, (p: SVGProps<SVGSVGElement>) => JSX.Element> = {
  vfx: IconSparkle,
  overlays: IconLayers,
  transiciones: IconPlay,
  animacion: IconAnim,
  fondos: IconImage,
  imagenes: IconImage,
  color: IconColor,
  plantillas: IconTemplate,
  audio: IconAudio,
  documentacion: IconDoc,
  otros: IconBox,
};
