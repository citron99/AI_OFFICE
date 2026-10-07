import React from "react";

/**
 * Минимальный набор inline-SVG-иконок (стиль lucide из дизайн-проекта).
 * Внешняя зависимость не добавляется: каждой иконке нужен только path.
 */
const paths = {
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: <><path d="M20 11a8 8 0 1 0-2.3 6.3" /><path d="M20 5v6h-6" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z" />,
  scale: <><path d="M12 3v18M5 7h14" /><path d="m5 7-3 7h6Zm14 0-3 7h6Z" /><path d="M8 21h8" /></>,
  calculator: <><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01" /></>,
  activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  bot: <><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4m-8 8H3m18 0h-3" /><path d="M9 13h.01M15 13h.01M9 17h6" /></>,
  network: <><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" /><path d="M12 7.5V12m0 0-5.5 5M12 12l5.5 5" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>,
  layers: <><path d="m12 3 9 5-9 5-9-5Z" /><path d="m4.5 12.8 7.5 4.2 7.5-4.2" /><path d="m4.5 16.8 7.5 4.2 7.5-4.2" /></>,
  chart: <><path d="M4 20V10m6 10V4m6 16v-7" /><path d="M2 20h20" /></>,
  wallet: <><rect x="3" y="6" width="18" height="14" rx="3" /><path d="M3 10h18M16 15h.01" /><path d="M15 6V4.5A1.5 1.5 0 0 0 13.5 3H6a3 3 0 0 0-3 3" /></>,
  arrowDown: <path d="M12 5v14m-6-6 6 6 6-6" />,
  alert: <><path d="M12 3 2.5 20h19Z" /><path d="M12 10v4m0 3h.01" /></>,
  check: <path d="m4.5 12.5 5 5 10-11" />,
  x: <path d="m6 6 12 12M18 6 6 18" />,
  shield: <><path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6Z" /><path d="m9 12 2 2 4-4" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5" /></>,
  chevronRight: <path d="m9 5 7 7-7 7" />,
  file: <><path d="M6 3h8l4 4v14H6Z" /><path d="M14 3v4h4M9 13h6M9 17h6" /></>,
  book: <><path d="M4 5a2 2 0 0 1 2-2h14v18H6a2 2 0 0 0-2 2Z" /><path d="M4 19a2 2 0 0 1 2-2h14" /></>,
};

/**
 * @param {{name: keyof typeof paths, size?: number, className?: string}} props
 */
export default function Icon({name, size = 16, className = "icon"}) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true">{paths[name] || null}</svg>;
}

/** Иконка бренда/маркера раздела. */
export function BrandIcon({name, size = 18}) {
  return <span className="ops-icon" aria-hidden="true"><Icon name={name} size={size} /></span>;
}
