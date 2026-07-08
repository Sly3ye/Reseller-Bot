export function eur(n: number): string {
  return "€" + Math.round(n).toLocaleString("it-IT");
}

/** Human "x min ago" style label from an ISO timestamp. */
export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `${min} min ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export type MarginTier = {
  label: string;
  color: string;
  bg: string;
};

/** Deal-quality badge derived from the real margin percentage. */
export function marginTier(pct: number | null): MarginTier {
  if (pct === null) {
    return { label: "n/d", color: "oklch(0.62 0.01 250)", bg: "oklch(0.46 0.01 250 / 0.14)" };
  }
  if (pct >= 20) {
    return { label: "Alto margine", color: "oklch(0.72 0.15 150)", bg: "oklch(0.72 0.15 150 / 0.14)" };
  }
  if (pct < 0) {
    return { label: "Sotto media", color: "oklch(0.68 0.19 25)", bg: "oklch(0.68 0.19 25 / 0.14)" };
  }
  return { label: "Margine medio", color: "oklch(0.75 0.14 75)", bg: "oklch(0.75 0.14 75 / 0.14)" };
}

/** Colour for the margin figure itself (green when strong, amber, red when negative). */
export function marginColor(pct: number | null): string {
  if (pct === null) return "oklch(0.62 0.01 250)";
  if (pct >= 20) return "oklch(0.72 0.16 150)";
  if (pct < 0) return "oklch(0.68 0.19 25)";
  return "oklch(0.75 0.13 80)";
}
