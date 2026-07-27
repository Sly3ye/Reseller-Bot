"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import {
  createDeal,
  deleteDeal,
  fetchAutomations,
  fetchDeals,
  fetchDealsSummary,
  fetchOpportunities,
  fetchScraperHealth,
  fetchSettings,
  fetchTrends,
  patchOpportunityStatus,
  pauseAutomation,
  rescheduleAutomation,
  resumeAutomation,
  runAutomation,
  setTriage,
  updateDeal,
  updateSettings,
  type ApiModelStat,
  type AppSettings,
  type ApiOpportunity,
  type ApiTrends,
  type AutomationJob,
  type Category,
  type Deal,
  type DealStage,
  type DealsSummary,
  type OpportunityFacets,
  type PresetMode,
  type ScraperHealth,
  type SellerRankRow,
  type SortMode,
  type ViewMode,
} from "@/lib/api";
import {
  dealClassStyle,
  eur,
  marginColor,
  marginTier,
  relativeTime,
  scoreColor,
} from "@/lib/flipradar-data";

const MONO = "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace";

type Vertical = "tech" | "auto";
type Screen = "sniper" | "intel" | "pipeline" | "automations" | "settings";
type MarginFilter = "all" | "high";

const PAGE_SIZE = 30;

const EMPTY_FACETS: OpportunityFacets = {
  models: [],
  storages: [],
  colors: [],
  conditions: [],
};

function buildTrendPaths(values: number[]) {
  if (values.length < 2) return null;
  const w = 600;
  const h = 200;
  const pad = 20;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = (w - pad * 2) / (values.length - 1);
  const points = values.map((v, i) => {
    const x = pad + i * stepX;
    const y = pad + (1 - (v - min) / range) * (h - pad * 2);
    return [x, y] as const;
  });
  const linePath = points
    .map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1))
    .join(" ");
  const last = points[points.length - 1];
  const first = points[0];
  const areaPath = `${linePath} L${last[0].toFixed(1)},${h - pad} L${first[0].toFixed(1)},${h - pad} Z`;
  return { linePath, areaPath, min, max };
}

export default function FlipRadar() {
  const [vertical, setVertical] = useState<Vertical>("tech");
  const [screen, setScreen] = useState<Screen>("sniper");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [flaggedIds, setFlaggedIds] = useState<Record<string, boolean>>({});
  const [lightbox, setLightbox] = useState<{ images: string[]; index: number } | null>(null);
  const [search, setSearch] = useState("");
  const [marginFilter, setMarginFilter] = useState<MarginFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("score");
  const [view, setView] = useState<ViewMode>("attivi");
  const [preset, setPreset] = useState<PresetMode | null>(null);

  // Filtri (iPhone) + paginazione, applicati lato server.
  const [fModel, setFModel] = useState<string | null>(null);
  const [fStorage, setFStorage] = useState<number | null>(null);
  const [fColor, setFColor] = useState<string | null>(null);
  const [fCondition, setFCondition] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const [opportunities, setOpportunities] = useState<ApiOpportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<OpportunityFacets>(EMPTY_FACETS);
  const [intel, setIntel] = useState<ApiTrends | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Caption "ultimo batch" nella Intelligence + countdown cosmetico sul feed.
  const batchLastRun = "03:00 (today)";
  const sniperInterval = 30;
  const [secondsToNextScan, setSecondsToNextScan] = useState(812);

  const [deals, setDeals] = useState<Deal[]>([]);
  const [dealsSummary, setDealsSummary] = useState<DealsSummary | null>(null);
  const [pipelineIds, setPipelineIds] = useState<Set<string>>(new Set());

  // Il toggle mostra "Auto", ma il backend usa la categoria nativa "automobile".
  const category: Category = vertical === "tech" ? "smartphone" : "automobile";

  // Market Intelligence: ricarica al cambio verticale.
  useEffect(() => {
    const controller = new AbortController();
    fetchTrends(category, controller.signal)
      .then(setIntel)
      .catch(() => {
        if (!controller.signal.aborted) setIntel(null);
      });
    return () => controller.abort();
  }, [category]);

  // Opportunità: TUTTE le attive, filtrate/ordinate/paginate lato server.
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setLoading(true);
      setError(null);
      setExpandedId(null);
    });

    fetchOpportunities(
      category,
      {
        sort: sortMode,
        model: fModel,
        storage: fStorage,
        color: fColor,
        condition: fCondition,
        minMargin: marginFilter === "high" ? 20 : null,
        q: search || null,
        view,
        preset,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      },
      controller.signal,
    )
      .then((res) => {
        setOpportunities(res.items);
        setTotal(res.total);
        setFacets(res.facets);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Errore di caricamento");
        setOpportunities([]);
        setTotal(0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [
    category, sortMode, fModel, fStorage, fColor, fCondition,
    marginFilter, search, view, preset, page,
  ]);

  useEffect(() => {
    const tick = setInterval(() => {
      setSecondsToNextScan((s) => (s > 0 ? s - 1 : sniperInterval * 60));
    }, 1000);
    return () => clearInterval(tick);
  }, [sniperInterval]);

  // Lightbox: chiusura con ESC, navigazione con frecce.
  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightbox(null);
      else if (e.key === "ArrowRight")
        setLightbox((lb) =>
          lb ? { ...lb, index: (lb.index + 1) % lb.images.length } : lb,
        );
      else if (e.key === "ArrowLeft")
        setLightbox((lb) =>
          lb ? { ...lb, index: (lb.index - 1 + lb.images.length) % lb.images.length } : lb,
        );
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const openLightbox = useCallback((images: string[], index: number) => {
    setLightbox({ images, index });
  }, []);

  const reloadDeals = useCallback(() => {
    Promise.all([fetchDeals(), fetchDealsSummary()])
      .then(([d, s]) => {
        setDeals(d);
        setDealsSummary(s);
        setPipelineIds(
          new Set(d.map((x) => x.listing_id).filter((x): x is string => !!x)),
        );
      })
      .catch(() => {
        /* pipeline vuota o backend giù: non è un errore bloccante */
      });
  }, []);

  useEffect(() => {
    reloadDeals();
  }, [reloadDeals]);

  const addToPipeline = useCallback(
    async (item: ApiOpportunity) => {
      try {
        await createDeal({
          category,
          listing_id: item.id,
          title: item.title ?? undefined,
          listing_url: item.url,
          asking_price: item.askingPrice ?? undefined,
          market_avg: item.marketAvg ?? undefined,
          offer_price: item.suggestedOffer ?? undefined,
        });
        setPipelineIds((cur) => new Set(cur).add(item.id));
        reloadDeals();
      } catch {
        /* già in pipeline o backend giù: ignora */
      }
    },
    [category, reloadDeals],
  );

  const markSeen = useCallback(
    (item: ApiOpportunity) => {
      if (item.status === "visto") return;
      patchOpportunityStatus(item.id, category, "visto").catch(() => {});
      setOpportunities((cur) =>
        cur.map((o) => (o.id === item.id ? { ...o, status: "visto" } : o)),
      );
    },
    [category],
  );

  // Azione sul feed: salva / scarta (toggle). Ottimistico + persistente.
  const triageItem = useCallback(
    (item: ApiOpportunity, action: "salvato" | "scartato") => {
      const next = item.triage === action ? null : action;
      setTriage(item.id, category, next).catch(() => {});
      setOpportunities((cur) => {
        // Se l'azione fa uscire l'annuncio dalla vista corrente, rimuovilo.
        if (next === "scartato" && view === "attivi") {
          return cur.filter((o) => o.id !== item.id);
        }
        if (next !== "salvato" && view === "salvati") {
          return cur.filter((o) => o.id !== item.id);
        }
        return cur.map((o) => (o.id === item.id ? { ...o, triage: next } : o));
      });
    },
    [category, view],
  );

  // Reset filtri + pagina al cambio verticale (i filtri sono tech-specifici).
  const resetFilters = useCallback(() => {
    setFModel(null);
    setFStorage(null);
    setFColor(null);
    setFCondition(null);
    setSearch("");
    setMarginFilter("all");
    setView("attivi");
    setPreset(null);
    setPage(0);
  }, []);
  const toggleVertical = () => {
    resetFilters();
    setVertical((v) => (v === "tech" ? "auto" : "tech"));
  };

  // Setter di filtro che riportano sempre alla prima pagina.
  const p0 = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(0);
  };

  const isTech = vertical === "tech";
  const accent = isTech ? "oklch(0.62 0.19 265)" : "oklch(0.68 0.19 45)";
  const accentSoft = isTech ? "oklch(0.62 0.19 265 / 0.16)" : "oklch(0.68 0.19 45 / 0.16)";
  const accentBorder = isTech ? "oklch(0.62 0.19 265 / 0.4)" : "oklch(0.68 0.19 45 / 0.4)";
  const accentText = isTech ? "oklch(0.80 0.13 265)" : "oklch(0.82 0.14 45)";

  // Il server già filtra/ordina/pagina: la lista mostrata è direttamente `opportunities`.
  const hasResults = opportunities.length > 0;

  const trendValues = useMemo(
    () => (intel?.trend ?? []).map((p) => p.price),
    [intel],
  );
  const trendPaths = useMemo(() => buildTrendPaths(trendValues), [trendValues]);

  const mm = Math.floor(secondsToNextScan / 60);
  const ss = secondsToNextScan % 60;
  const nextScanLabel = `${mm}:${String(ss).padStart(2, "0")}`;

  const rootStyle: CSSProperties = {
    ["--accent" as string]: accent,
    ["--accent-soft" as string]: accentSoft,
    ["--accent-border" as string]: accentBorder,
    ["--accent-text" as string]: accentText,
    fontFamily: "var(--font-ibm-plex-sans), 'IBM Plex Sans', sans-serif",
    background: "oklch(0.15 0.008 250)",
    color: "oklch(0.94 0.004 250)",
    height: "100vh",
    width: "100%",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  };

  const navItem = (active: boolean): CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "10px 12px",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: 500,
    background: active ? "var(--accent-soft)" : "transparent",
    color: active ? "var(--accent-text)" : "oklch(0.62 0.01 250)",
  });

  return (
    <div style={rootStyle}>
      {/* TOPBAR */}
      <div
        style={{
          height: "64px",
          minHeight: "64px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 24px",
          background: "oklch(0.18 0.008 250)",
          borderBottom: "1px solid oklch(0.27 0.01 250)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "7px",
              background: "var(--accent)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "50%",
                border: "2px solid oklch(0.15 0.008 250)",
              }}
            />
          </div>
          <div style={{ fontFamily: MONO, fontSize: "15px", fontWeight: 600, letterSpacing: "0.02em" }}>
            FLIPRADAR
          </div>
          <div
            style={{
              fontSize: "12px",
              color: "oklch(0.46 0.01 250)",
              fontFamily: MONO,
              marginLeft: "4px",
              padding: "2px 8px",
              border: "1px solid oklch(0.32 0.01 250)",
              borderRadius: "4px",
            }}
          >
            v0.9 internal
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <div style={{ fontSize: "12px", color: "oklch(0.62 0.01 250)", fontWeight: 500 }}>Business:</div>
          <div
            onClick={toggleVertical}
            style={{
              position: "relative",
              width: "176px",
              height: "36px",
              background: "oklch(0.24 0.008 250)",
              border: "1px solid oklch(0.32 0.01 250)",
              borderRadius: "10px",
              display: "flex",
              alignItems: "center",
              padding: "3px",
              cursor: "pointer",
            }}
          >
            <div
              style={{
                position: "absolute",
                top: "3px",
                left: isTech ? "3px" : "89px",
                width: "84px",
                height: "28px",
                background: "var(--accent)",
                borderRadius: "7px",
                transition: "left 0.25s ease",
              }}
            />
            <div
              style={{
                position: "relative",
                zIndex: 1,
                width: "84px",
                textAlign: "center",
                fontSize: "13px",
                fontWeight: 600,
                color: isTech ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
              }}
            >
              📱 Tech
            </div>
            <div
              style={{
                position: "relative",
                zIndex: 1,
                width: "84px",
                textAlign: "center",
                fontSize: "13px",
                fontWeight: 600,
                color: !isTech ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
              }}
            >
              🚗 Auto
            </div>
          </div>
        </div>
      </div>

      {/* BODY */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* SIDEBAR */}
        <div
          style={{
            width: "232px",
            minWidth: "232px",
            background: "oklch(0.17 0.008 250)",
            borderRight: "1px solid oklch(0.27 0.01 250)",
            padding: "16px 12px",
            display: "flex",
            flexDirection: "column",
            gap: "2px",
          }}
        >
          <div
            style={{
              fontSize: "11px",
              fontWeight: 600,
              letterSpacing: "0.08em",
              color: "oklch(0.46 0.01 250)",
              textTransform: "uppercase",
              padding: "8px 10px 6px",
            }}
          >
            Workspace
          </div>

          <div onClick={() => setScreen("sniper")} style={navItem(screen === "sniper")}>
            <div
              style={{
                width: "16px",
                height: "16px",
                borderRadius: "50%",
                border: "2px solid currentColor",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <div style={{ width: "4px", height: "4px", borderRadius: "50%", background: "currentColor" }} />
            </div>
            Live Sniper
          </div>

          <div onClick={() => setScreen("intel")} style={navItem(screen === "intel")}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: "2px",
                width: "16px",
                height: "16px",
                flexShrink: 0,
              }}
            >
              <div style={{ width: "3px", height: "6px", background: "currentColor" }} />
              <div style={{ width: "3px", height: "11px", background: "currentColor" }} />
              <div style={{ width: "3px", height: "16px", background: "currentColor" }} />
            </div>
            Market Intelligence
          </div>

          <div onClick={() => setScreen("pipeline")} style={navItem(screen === "pipeline")}>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                width: "16px",
                height: "16px",
                flexShrink: 0,
              }}
            >
              <div style={{ width: "16px", height: "3px", borderRadius: "2px", background: "currentColor" }} />
              <div style={{ width: "11px", height: "3px", borderRadius: "2px", background: "currentColor" }} />
              <div style={{ width: "6px", height: "3px", borderRadius: "2px", background: "currentColor" }} />
            </div>
            Pipeline P&amp;L
            {deals.length > 0 && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: "11px",
                  fontFamily: MONO,
                  padding: "1px 7px",
                  borderRadius: "10px",
                  background: "var(--accent-soft)",
                  color: "var(--accent-text)",
                }}
              >
                {deals.length}
              </span>
            )}
          </div>

          <div onClick={() => setScreen("automations")} style={navItem(screen === "automations")}>
            <div
              style={{
                width: "16px",
                height: "16px",
                border: "2px solid currentColor",
                borderRadius: "4px",
                flexShrink: 0,
              }}
            />
            Automations
          </div>

          <div onClick={() => setScreen("settings")} style={navItem(screen === "settings")}>
            <div
              style={{
                width: "16px",
                height: "16px",
                border: "2px solid currentColor",
                borderRadius: "50%",
                flexShrink: 0,
              }}
            />
            Impostazioni
          </div>

          <div style={{ flex: 1 }} />

          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: "oklch(0.21 0.008 250)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11px",
                color: "oklch(0.62 0.01 250)",
                fontWeight: 600,
              }}
            >
              <div
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  background: "oklch(0.72 0.16 150)",
                  animation: "pulseDot 2s ease-in-out infinite",
                }}
              />
              SNIPER ENGINE LIVE
            </div>
            <div style={{ fontSize: "11px", color: "oklch(0.46 0.01 250)", fontFamily: MONO }}>
              next scan in {nextScanLabel}
            </div>
          </div>
        </div>

        {/* MAIN */}
        <div style={{ flex: 1, overflowY: "auto", padding: "28px 32px 60px" }}>
          {screen === "sniper" && (
            <SniperScreen
              total={total}
              isTech={isTech}
              category={category}
              facets={facets}
              search={search}
              onSearchChange={p0(setSearch)}
              marginFilter={marginFilter}
              onFilterChange={p0(setMarginFilter)}
              sortMode={sortMode}
              onSortChange={p0(setSortMode)}
              view={view}
              onViewChange={p0(setView)}
              preset={preset}
              onPresetChange={p0(setPreset)}
              onTriage={triageItem}
              fModel={fModel}
              onModelChange={p0(setFModel)}
              fStorage={fStorage}
              onStorageChange={p0(setFStorage)}
              fColor={fColor}
              onColorChange={p0(setFColor)}
              fCondition={fCondition}
              onConditionChange={p0(setFCondition)}
              page={page}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
              loading={loading}
              error={error}
              hasResults={hasResults}
              listings={opportunities}
              expandedId={expandedId}
              flaggedIds={flaggedIds}
              pipelineIds={pipelineIds}
              onToggleExpand={(id) => {
                setExpandedId((cur) => (cur === id ? null : id));
                const item = opportunities.find((x) => x.id === id);
                if (item && expandedId !== id) markSeen(item);
              }}
              onToggleFlag={(id) => setFlaggedIds((cur) => ({ ...cur, [id]: !cur[id] }))}
              onAddToPipeline={addToPipeline}
              onImageClick={openLightbox}
            />
          )}

          {screen === "intel" && (
            <IntelScreen
              loading={loading}
              error={error}
              intel={intel}
              trendPaths={trendPaths}
              batchLastRun={batchLastRun}
            />
          )}

          {screen === "pipeline" && (
            <PipelineScreen
              deals={deals}
              summary={dealsSummary}
              onUpdate={async (id, patch) => {
                await updateDeal(id, patch);
                reloadDeals();
              }}
              onDelete={async (id) => {
                await deleteDeal(id);
                reloadDeals();
              }}
            />
          )}

          {screen === "automations" && <AutomationsScreen />}

          {screen === "settings" && <SettingsScreen />}
        </div>
      </div>

      {lightbox && (
        <Lightbox
          images={lightbox.images}
          index={lightbox.index}
          onClose={() => setLightbox(null)}
          onNav={(delta) =>
            setLightbox((lb) =>
              lb
                ? { ...lb, index: (lb.index + delta + lb.images.length) % lb.images.length }
                : lb,
            )
          }
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- shared */

/** Lightbox immagini: overlay a schermo, chiudibile con X, ESC o click sfondo. */
function Lightbox(props: {
  images: string[];
  index: number;
  onClose: () => void;
  onNav: (delta: number) => void;
}) {
  const src = props.images[props.index];
  return (
    <div
      onClick={props.onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "oklch(0.08 0.008 250 / 0.9)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px",
      }}
    >
      <button
        onClick={props.onClose}
        aria-label="Chiudi"
        style={{
          position: "absolute",
          top: "18px",
          right: "22px",
          width: "40px",
          height: "40px",
          borderRadius: "50%",
          border: "1px solid oklch(0.4 0.01 250)",
          background: "oklch(0.18 0.008 250)",
          color: "oklch(0.94 0.004 250)",
          fontSize: "20px",
          cursor: "pointer",
        }}
      >
        ✕
      </button>
      {props.images.length > 1 && (
        <>
          <button
            onClick={(e) => {
              e.stopPropagation();
              props.onNav(-1);
            }}
            aria-label="Precedente"
            style={{ ...LIGHTBOX_ARROW, left: "18px" }}
          >
            ‹
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              props.onNav(1);
            }}
            aria-label="Successiva"
            style={{ ...LIGHTBOX_ARROW, right: "18px" }}
          >
            ›
          </button>
        </>
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        onClick={(e) => e.stopPropagation()}
        style={{
          maxWidth: "100%",
          maxHeight: "100%",
          objectFit: "contain",
          borderRadius: "8px",
          boxShadow: "0 8px 40px oklch(0 0 0 / 0.5)",
        }}
      />
      {props.images.length > 1 && (
        <div
          style={{
            position: "absolute",
            bottom: "20px",
            fontFamily: MONO,
            fontSize: "13px",
            color: "oklch(0.7 0.01 250)",
          }}
        >
          {props.index + 1} / {props.images.length}
        </div>
      )}
    </div>
  );
}

const LIGHTBOX_ARROW: CSSProperties = {
  position: "absolute",
  top: "50%",
  transform: "translateY(-50%)",
  width: "44px",
  height: "44px",
  borderRadius: "50%",
  border: "1px solid oklch(0.4 0.01 250)",
  background: "oklch(0.18 0.008 250)",
  color: "oklch(0.94 0.004 250)",
  fontSize: "26px",
  lineHeight: 1,
  cursor: "pointer",
};

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: "10px",
        border: "1px solid oklch(0.68 0.19 25 / 0.4)",
        background: "oklch(0.68 0.19 25 / 0.1)",
        color: "oklch(0.82 0.12 25)",
        fontSize: "13px",
      }}
    >
      Impossibile contattare il backend ({message}). Verifica che l&apos;API sia attiva su{" "}
      <span style={{ fontFamily: MONO }}>http://localhost:8000</span>.
    </div>
  );
}

/* ---------------------------------------------------------------- SNIPER */

const GRID_COLUMNS = "56px 60px 2.1fr 1fr 1fr 1.1fr 84px 104px";

function SniperScreen(props: {
  total: number;
  isTech: boolean;
  category: Category;
  facets: OpportunityFacets;
  search: string;
  onSearchChange: (v: string) => void;
  marginFilter: MarginFilter;
  onFilterChange: (v: MarginFilter) => void;
  sortMode: SortMode;
  onSortChange: (v: SortMode) => void;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
  preset: PresetMode | null;
  onPresetChange: (v: PresetMode | null) => void;
  onTriage: (item: ApiOpportunity, action: "salvato" | "scartato") => void;
  fModel: string | null;
  onModelChange: (v: string | null) => void;
  fStorage: number | null;
  onStorageChange: (v: number | null) => void;
  fColor: string | null;
  onColorChange: (v: string | null) => void;
  fCondition: string | null;
  onConditionChange: (v: string | null) => void;
  page: number;
  pageSize: number;
  onPageChange: (v: number) => void;
  loading: boolean;
  error: string | null;
  hasResults: boolean;
  listings: ApiOpportunity[];
  expandedId: string | null;
  flaggedIds: Record<string, boolean>;
  pipelineIds: Set<string>;
  onToggleExpand: (id: string) => void;
  onToggleFlag: (id: string) => void;
  onAddToPipeline: (item: ApiOpportunity) => void;
  onImageClick: (images: string[], index: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(props.total / props.pageSize));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.2s ease" }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: "16px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: "22px", fontWeight: 700 }}>Opportunità</div>
          <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
            {props.total} opportunità · le migliori per Deal Score, con filtri
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <input
            value={props.search}
            onChange={(e) => props.onSearchChange(e.target.value)}
            placeholder="Search title or city..."
            style={{
              width: "240px",
              height: "36px",
              background: "oklch(0.20 0.008 250)",
              border: "1px solid oklch(0.32 0.01 250)",
              borderRadius: "8px",
              padding: "0 12px",
              color: "oklch(0.94 0.004 250)",
              fontSize: "13px",
              fontFamily: "inherit",
            }}
          />
          <div
            style={{
              display: "flex",
              background: "oklch(0.20 0.008 250)",
              border: "1px solid oklch(0.32 0.01 250)",
              borderRadius: "8px",
              padding: "3px",
              gap: "2px",
            }}
          >
            <div
              onClick={() => props.onFilterChange("all")}
              style={{
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                background: props.marginFilter === "all" ? "var(--accent)" : "transparent",
                color: props.marginFilter === "all" ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
              }}
            >
              All
            </div>
            <div
              onClick={() => props.onFilterChange("high")}
              style={{
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                whiteSpace: "nowrap",
                background: props.marginFilter === "high" ? "var(--accent)" : "transparent",
                color: props.marginFilter === "high" ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
              }}
            >
              Margin &gt; 20%
            </div>
          </div>
          <div
            style={{
              display: "flex",
              background: "oklch(0.20 0.008 250)",
              border: "1px solid oklch(0.32 0.01 250)",
              borderRadius: "8px",
              padding: "3px",
              gap: "2px",
            }}
          >
            {(["score", "roi", "recent", "margin"] as SortMode[]).map((mode) => (
              <div
                key={mode}
                onClick={() => props.onSortChange(mode)}
                style={{
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: 600,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  background: props.sortMode === mode ? "var(--accent)" : "transparent",
                  color: props.sortMode === mode ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
                }}
              >
                {mode === "score" ? "Deal Score" : mode === "roi" ? "ROI/gg" : mode === "recent" ? "Recenti" : "Margine"}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Vista triage (attivi/salvati/tutti) + preset rapidi */}
      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
        <div
          style={{
            display: "flex",
            background: "oklch(0.20 0.008 250)",
            border: "1px solid oklch(0.32 0.01 250)",
            borderRadius: "8px",
            padding: "3px",
            gap: "2px",
          }}
        >
          {([
            ["attivi", "Attivi"],
            ["salvati", "⭐ Salvati"],
            ["tutti", "Tutti"],
          ] as [ViewMode, string][]).map(([v, label]) => (
            <div
              key={v}
              onClick={() => props.onViewChange(v)}
              style={{
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                whiteSpace: "nowrap",
                background: props.view === v ? "var(--accent)" : "transparent",
                color: props.view === v ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
              }}
            >
              {label}
            </div>
          ))}
        </div>
        {([
          ["compra_ora", "🟢 Compra ora"],
          ["motivati", "🎯 Motivati"],
          ["riparabili", "🔧 Riparabili"],
        ] as [PresetMode, string][]).map(([pkey, label]) => {
          const active = props.preset === pkey;
          return (
            <div
              key={pkey}
              onClick={() => props.onPresetChange(active ? null : pkey)}
              style={{
                padding: "7px 12px",
                borderRadius: "8px",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
                whiteSpace: "nowrap",
                background: active ? "var(--accent)" : "oklch(0.20 0.008 250)",
                border: "1px solid " + (active ? "var(--accent)" : "oklch(0.32 0.01 250)"),
                color: active ? "oklch(0.12 0.008 250)" : "oklch(0.72 0.01 250)",
              }}
            >
              {label}
            </div>
          );
        })}
      </div>

      {/* Barra filtri (iPhone): modello, memoria, colore, condizione — da facets */}
      {props.isTech && (
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          <FacetSelect
            label="Modello"
            value={props.fModel}
            onChange={props.onModelChange}
            options={props.facets.models.map((m) => ({ value: m.key, label: `${m.label} (${m.count})` }))}
          />
          <FacetSelect
            label="Memoria"
            value={props.fStorage === null ? null : String(props.fStorage)}
            onChange={(v) => props.onStorageChange(v === null ? null : Number(v))}
            options={props.facets.storages.map((s) => ({
              value: String(s.value),
              label: `${s.value >= 1024 ? "1TB" : s.value + "GB"} (${s.count})`,
            }))}
          />
          <FacetSelect
            label="Colore"
            value={props.fColor}
            onChange={props.onColorChange}
            options={props.facets.colors.map((c) => ({ value: c.value, label: `${c.value} (${c.count})` }))}
          />
          <FacetSelect
            label="Condizione"
            value={props.fCondition}
            onChange={props.onConditionChange}
            options={props.facets.conditions.map((c) => ({ value: c.value, label: `${c.value} (${c.count})` }))}
          />
          {(props.fModel || props.fStorage !== null || props.fColor || props.fCondition) && (
            <button
              onClick={() => {
                props.onModelChange(null);
                props.onStorageChange(null);
                props.onColorChange(null);
                props.onConditionChange(null);
              }}
              style={{
                height: "34px",
                padding: "0 12px",
                borderRadius: "8px",
                border: "1px solid oklch(0.32 0.01 250)",
                background: "transparent",
                color: "oklch(0.72 0.16 30)",
                fontSize: "12px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              ✕ Azzera filtri
            </button>
          )}
        </div>
      )}

      {props.error ? (
        <ErrorBanner message={props.error} />
      ) : props.loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {[0, 1, 2, 3, 4, 5].map((row) => (
            <div
              key={row}
              style={{
                height: "64px",
                borderRadius: "10px",
                background:
                  "linear-gradient(90deg, oklch(0.19 0.008 250), oklch(0.23 0.008 250), oklch(0.19 0.008 250))",
                backgroundSize: "200% 100%",
                animation: "pulseDot 1.4s ease-in-out infinite",
              }}
            />
          ))}
        </div>
      ) : props.hasResults ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            border: "1px solid oklch(0.27 0.01 250)",
            borderRadius: "12px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: GRID_COLUMNS,
              gap: "12px",
              padding: "10px 16px",
              background: "oklch(0.20 0.008 250)",
              fontSize: "11px",
              fontWeight: 600,
              color: "oklch(0.46 0.01 250)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            <div />
            <div>Score</div>
            <div>Item</div>
            <div>Asking</div>
            <div>Market Avg</div>
            <div>Est. Margin</div>
            <div>Found</div>
            <div />
          </div>

          {props.listings.map((item) => (
            <SniperRow
              key={item.id}
              item={item}
              category={props.category}
              expanded={props.expandedId === item.id}
              flagged={!!props.flaggedIds[item.id]}
              inPipeline={props.pipelineIds.has(item.id)}
              onToggle={() => props.onToggleExpand(item.id)}
              onFlag={() => props.onToggleFlag(item.id)}
              onAddToPipeline={() => props.onAddToPipeline(item)}
              onTriage={props.onTriage}
              onImageClick={props.onImageClick}
            />
          ))}
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "70px 20px",
            border: "1px dashed oklch(0.32 0.01 250)",
            borderRadius: "12px",
            gap: "8px",
          }}
        >
          <div style={{ width: "40px", height: "40px", borderRadius: "50%", border: "2px solid oklch(0.32 0.01 250)" }} />
          <div style={{ fontSize: "14px", fontWeight: 600, color: "oklch(0.62 0.01 250)" }}>
            No opportunities match your filters
          </div>
          <div style={{ fontSize: "12.5px", color: "oklch(0.46 0.01 250)" }}>
            Prova ad azzerare la ricerca o i filtri
          </div>
        </div>
      )}

      {/* Paginazione */}
      {props.hasResults && pageCount > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "14px", paddingTop: "4px" }}>
          <button
            onClick={() => props.onPageChange(props.page - 1)}
            disabled={props.page <= 0}
            style={{
              height: "34px", padding: "0 14px", borderRadius: "8px",
              border: "1px solid oklch(0.32 0.01 250)", background: "oklch(0.20 0.008 250)",
              color: props.page <= 0 ? "oklch(0.40 0.01 250)" : "oklch(0.90 0.004 250)",
              fontSize: "13px", fontWeight: 600, cursor: props.page <= 0 ? "default" : "pointer",
            }}
          >
            ← Prec
          </button>
          <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", fontFamily: MONO }}>
            Pagina {props.page + 1} / {pageCount}
          </div>
          <button
            onClick={() => props.onPageChange(props.page + 1)}
            disabled={props.page >= pageCount - 1}
            style={{
              height: "34px", padding: "0 14px", borderRadius: "8px",
              border: "1px solid oklch(0.32 0.01 250)", background: "oklch(0.20 0.008 250)",
              color: props.page >= pageCount - 1 ? "oklch(0.40 0.01 250)" : "oklch(0.90 0.004 250)",
              fontSize: "13px", fontWeight: 600, cursor: props.page >= pageCount - 1 ? "default" : "pointer",
            }}
          >
            Succ →
          </button>
        </div>
      )}
    </div>
  );
}

/** Select nativo per un filtro a faccette (opzione vuota = "Tutti"). */
function FacetSelect(props: {
  label: string;
  value: string | null;
  onChange: (v: string | null) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={props.value ?? ""}
      onChange={(e) => props.onChange(e.target.value === "" ? null : e.target.value)}
      style={{
        height: "34px",
        background: props.value ? "var(--accent-soft)" : "oklch(0.20 0.008 250)",
        border: `1px solid ${props.value ? "var(--accent-border)" : "oklch(0.32 0.01 250)"}`,
        borderRadius: "8px",
        padding: "0 10px",
        color: props.value ? "var(--accent-text)" : "oklch(0.80 0.004 250)",
        fontSize: "13px",
        fontFamily: "inherit",
        cursor: "pointer",
        maxWidth: "220px",
      }}
    >
      <option value="">{props.label}: tutti</option>
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function SniperRow(props: {
  item: ApiOpportunity;
  category: Category;
  expanded: boolean;
  flagged: boolean;
  inPipeline: boolean;
  onToggle: () => void;
  onFlag: () => void;
  onAddToPipeline: () => void;
  onTriage: (item: ApiOpportunity, action: "salvato" | "scartato") => void;
  onImageClick: (images: string[], index: number) => void;
}) {
  const { item, expanded, flagged } = props;
  const tier = marginTier(item.marginPct);
  const mColor = marginColor(item.marginPct);
  const sColor = scoreColor(item.score ?? 0);
  const rowBg = expanded
    ? "oklch(0.22 0.008 250)"
    : flagged
      ? "oklch(0.68 0.19 25 / 0.06)"
      : "transparent";
  const flagColor = flagged ? "oklch(0.72 0.19 25)" : "oklch(0.46 0.01 250)";

  const askingLabel = item.askingPrice !== null ? eur(item.askingPrice) : "—";
  const avgLabel = item.marketAvg !== null ? eur(item.marketAvg) : "—";
  const marginEurLabel =
    item.marginEur !== null ? (item.marginEur >= 0 ? "+" : "") + eur(item.marginEur) : "—";
  const marginPctLabel =
    item.marginPct !== null ? (item.marginPct >= 0 ? "+" : "") + Math.round(item.marginPct) + "%" : "—";
  const locationLabel = item.location ?? item.source ?? "";

  return (
    <div style={{ borderTop: "1px solid oklch(0.24 0.008 250)" }}>
      <div
        onClick={props.onToggle}
        style={{
          display: "grid",
          gridTemplateColumns: GRID_COLUMNS,
          gap: "12px",
          padding: "12px 16px",
          alignItems: "center",
          cursor: "pointer",
          background: rowBg,
          opacity: flagged ? 0.55 : 1,
        }}
      >
        <div
          style={{
            width: "44px",
            height: "44px",
            borderRadius: "8px",
            overflow: "hidden",
            border: "1px solid oklch(0.32 0.01 250)",
            background:
              "repeating-linear-gradient(135deg, oklch(0.27 0.01 250), oklch(0.27 0.01 250) 4px, oklch(0.23 0.008 250) 4px, oklch(0.23 0.008 250) 8px)",
          }}
        >
          {item.images[0] && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={item.images[0]}
              alt=""
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          )}
        </div>
        <div
          title="Deal Score (0–100)"
          style={{
            width: "44px",
            height: "44px",
            borderRadius: "10px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            background: sColor.bg,
            border: `1px solid ${sColor.color}`,
          }}
        >
          <div style={{ fontFamily: MONO, fontSize: "16px", fontWeight: 700, color: sColor.color, lineHeight: 1 }}>
            {item.score ?? 0}
          </div>
          <div style={{ fontSize: "8px", color: sColor.color, textTransform: "uppercase", letterSpacing: "0.05em", marginTop: "1px" }}>
            score
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: "13.5px",
              fontWeight: 600,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {item.title ?? "—"}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "3px", minWidth: 0 }}>
            <div
              style={{
                fontSize: "11px",
                padding: "1px 7px",
                borderRadius: "4px",
                background: tier.bg,
                color: tier.color,
                fontWeight: 600,
                whiteSpace: "nowrap",
                flexShrink: 0,
              }}
            >
              {tier.label}
            </div>
            {(() => {
              const dc = dealClassStyle(item.dealClass);
              return dc ? (
                <div
                  style={{
                    fontSize: "11px",
                    padding: "1px 7px",
                    borderRadius: "4px",
                    background: dc.bg,
                    color: dc.color,
                    fontWeight: 600,
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}
                >
                  {dc.label}
                </div>
              ) : null;
            })()}
            {item.buyAtAsking && item.dealClass !== "sospetto" && (
              <div
                style={{
                  fontSize: "11px",
                  padding: "1px 7px",
                  borderRadius: "4px",
                  background: "oklch(0.72 0.16 150 / 0.16)",
                  color: "oklch(0.80 0.15 150)",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
                title="Il prezzo richiesto è già sotto il tetto d'acquisto: conviene anche senza trattare"
              >
                🟢 compra ora
              </div>
            )}
            {item.urgencyFlags.length > 0 && (
              <div
                style={{
                  fontSize: "11px",
                  padding: "1px 7px",
                  borderRadius: "4px",
                  background: "oklch(0.68 0.19 25 / 0.14)",
                  color: "oklch(0.78 0.16 30)",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
              >
                🔥 urgente
              </div>
            )}
            {item.repair && (
              <div
                style={{
                  fontSize: "11px",
                  padding: "1px 7px",
                  borderRadius: "4px",
                  background: "oklch(0.75 0.14 75 / 0.16)",
                  color: "oklch(0.80 0.13 75)",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
              >
                🔧 da riparare
              </div>
            )}
            <div
              style={{
                fontSize: "11.5px",
                color: "oklch(0.46 0.01 250)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                minWidth: 0,
              }}
            >
              {[
                item.storageGb ? `${item.storageGb} GB` : null,
                item.color,
                item.batteryPct ? `🔋${item.batteryPct}%` : null,
                item.km ? `${Math.round(item.km / 1000)}k km` : null,
                locationLabel,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
        </div>
        <div style={{ fontFamily: MONO, fontSize: "13.5px", fontWeight: 600 }}>{askingLabel}</div>
        <div>
          <div
            style={{
              display: "inline-block",
              fontFamily: MONO,
              fontSize: "12px",
              padding: "3px 8px",
              borderRadius: "5px",
              background: "oklch(0.24 0.008 250)",
              border: "1px solid oklch(0.32 0.01 250)",
            }}
          >
            {avgLabel}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: MONO, fontSize: "13.5px", fontWeight: 700, color: mColor }}>
            {marginEurLabel}
          </div>
          <div style={{ fontFamily: MONO, fontSize: "11px", fontWeight: 600, color: mColor }}>
            {marginPctLabel}
          </div>
        </div>
        <div style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)", fontFamily: MONO }}>
          {relativeTime(item.foundAt)}
        </div>
        <div style={{ display: "flex", gap: "4px", alignItems: "center", justifyContent: "flex-end" }}>
          <div
            onClick={(e) => {
              e.stopPropagation();
              props.onTriage(item, "salvato");
            }}
            title={item.triage === "salvato" ? "Rimuovi dai salvati" : "Salva"}
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "7px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              fontSize: "13px",
              background: item.triage === "salvato" ? "oklch(0.78 0.14 85 / 0.20)" : "transparent",
              filter: item.triage === "salvato" ? "none" : "grayscale(1) opacity(0.5)",
            }}
          >
            ⭐
          </div>
          <div
            onClick={(e) => {
              e.stopPropagation();
              props.onTriage(item, "scartato");
            }}
            title={item.triage === "scartato" ? "Ripristina" : "Scarta (nascondi)"}
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "7px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              fontSize: "13px",
              color: item.triage === "scartato" ? "oklch(0.78 0.16 30)" : "oklch(0.5 0.01 250)",
              background: item.triage === "scartato" ? "oklch(0.68 0.19 25 / 0.16)" : "transparent",
            }}
          >
            🗑
          </div>
          <div
            onClick={(e) => {
              e.stopPropagation();
              props.onFlag();
            }}
            title="Segnala truffa/errore"
            style={{
              width: "28px",
              height: "28px",
              borderRadius: "7px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              background: flagged ? "oklch(0.68 0.19 25 / 0.18)" : "transparent",
            }}
          >
            <div style={{ width: "10px", height: "10px", borderLeft: `2px solid ${flagColor}`, position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  left: "-1px",
                  top: "-1px",
                  width: "8px",
                  height: "5px",
                  background: flagColor,
                  clipPath: "polygon(0 0, 100% 25%, 0 50%)",
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            padding: "16px 20px 22px 96px",
            background: "oklch(0.185 0.008 250)",
            borderTop: "1px solid oklch(0.24 0.008 250)",
            display: "flex",
            flexDirection: "column",
            gap: "14px",
          }}
        >
          <NegotiationAssistant
            item={item}
            category={props.category}
            inPipeline={props.inPipeline}
            onAddToPipeline={props.onAddToPipeline}
          />
          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                color: "oklch(0.46 0.01 250)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                marginBottom: "6px",
              }}
            >
              Full scraped description
            </div>
            <div
              style={{
                background: "oklch(0.16 0.008 250)",
                border: "1px solid oklch(0.27 0.01 250)",
                borderRadius: "8px",
                padding: "12px 14px",
                fontFamily: MONO,
                fontSize: "12.5px",
                lineHeight: 1.6,
                color: "oklch(0.82 0.008 250)",
                whiteSpace: "pre-wrap",
              }}
            >
              {item.description ?? "Nessuna descrizione disponibile."}
            </div>
          </div>
          <div>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                color: "oklch(0.46 0.01 250)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                marginBottom: "6px",
              }}
            >
              Gallery ({item.images.length})
            </div>
            {item.images.length > 0 ? (
              <div style={{ display: "flex", gap: "10px", overflowX: "auto", paddingBottom: "4px" }}>
                {item.images.map((src, i) => (
                  <div
                    key={item.id + "-" + i}
                    onClick={() => props.onImageClick(item.images, i)}
                    style={{
                      minWidth: "140px",
                      width: "140px",
                      height: "100px",
                      borderRadius: "8px",
                      flexShrink: 0,
                      overflow: "hidden",
                      border: "1px solid oklch(0.32 0.01 250)",
                      display: "block",
                      cursor: "zoom-in",
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={src}
                      alt={`foto ${i + 1}`}
                      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: "12.5px", color: "oklch(0.46 0.01 250)" }}>
                Nessuna immagine salvata per questo annuncio.
              </div>
            )}
          </div>
          {item.url && (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: "12.5px", color: "var(--accent-text)", fontWeight: 600, textDecoration: "none" }}
            >
              Apri annuncio originale →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------- NEGOTIATION ASSISTANT */

function NegotiationAssistant(props: {
  item: ApiOpportunity;
  category: Category;
  inPipeline: boolean;
  onAddToPipeline: () => void;
}) {
  const { item } = props;

  const sourceLabel: Record<string, string> = {
    venduti: "dai venduti",
    km: "prezzo~km",
    listati: "dai listati",
  };

  const stats: { label: string; value: string; hint?: string; color?: string }[] = [];
  if (item.fairValue !== null) {
    const base = item.fairValueSource ? sourceLabel[item.fairValueSource] : null;
    const conf = item.valuationConfidence
      ? `affidabilità ${item.valuationConfidence}` +
        (item.valuationSamples ? ` (${item.valuationSamples} campioni)` : "")
      : null;
    const parts = [
      item.marginVsFairPct !== null
        ? `${item.marginVsFairPct >= 0 ? "+" : ""}${item.marginVsFairPct}% vs richiesto`
        : null,
      item.pricePosition !== null
        ? `più economico del ${Math.round(100 - item.pricePosition)}%`
        : null,
      base,
      conf,
    ].filter(Boolean);
    stats.push({
      label: "Valore equo stimato",
      value: eur(item.fairValue),
      hint: parts.length ? parts.join(" · ") : undefined,
      color:
        item.dealClass === "affare"
          ? "oklch(0.75 0.15 150)"
          : item.dealClass === "sospetto"
            ? "oklch(0.75 0.17 30)"
            : "var(--accent-text)",
    });
  }
  if (item.maxBid !== null) {
    stats.push({
      label: "Prezzo d'acquisto max",
      value: eur(item.maxBid),
      hint: item.buyAtAsking
        ? "✓ conviene anche al prezzo richiesto"
        : "tetto per centrare il margine obiettivo",
      color: item.buyAtAsking ? "oklch(0.75 0.15 150)" : "oklch(0.80 0.13 75)",
    });
  }
  if (item.suggestedOffer !== null) {
    stats.push({
      label: "Offerta consigliata",
      value: eur(item.suggestedOffer),
      hint: "prezzo di apertura trattativa",
      color: "var(--accent-text)",
    });
  }
  if (item.roiPerDayPct !== null) {
    stats.push({
      label: "ROI / giorno di capitale",
      value: `${item.roiPerDayPct >= 0 ? "+" : ""}${item.roiPerDayPct}%/gg`,
      hint: "margine ÷ giorni medi di vendita",
      color: "oklch(0.78 0.14 195)",
    });
  }
  if (item.daysOnline !== null) {
    stats.push({
      label: "Online da",
      value: `${item.daysOnline} ${item.daysOnline === 1 ? "giorno" : "giorni"}`,
      hint: item.daysOnline >= 14 ? "invenduto: più margine di trattativa" : "annuncio recente",
    });
  }
  if (item.priceDrop && item.priceDrop.oldPrice && item.priceDrop.newPrice) {
    stats.push({
      label: "Già ribassato",
      value: `${eur(item.priceDrop.oldPrice)} → ${eur(item.priceDrop.newPrice)}`,
      hint: "il venditore sta scendendo",
      color: "oklch(0.72 0.16 150)",
    });
  }
  if (item.sellerType) {
    const label =
      item.sellerType === "finto_privato"
        ? "⚠️ finto privato"
        : item.sellerType === "dealer"
          ? "concessionario"
          : "privato";
    const p = item.sellerProfile;
    const bits: string[] = [];
    if (p) {
      if (p.active) bits.push(`${p.active} attivi`);
      if (p.sold) {
        bits.push(
          `${p.sold} venduti` + (p.avgDaysToSell != null ? ` in ~${p.avgDaysToSell}gg` : ""),
        );
      }
      if (p.dropRate >= 20) {
        bits.push(
          `ribassa nel ${p.dropRate}%` + (p.avgDropPct != null ? ` (−${p.avgDropPct}%)` : ""),
        );
      }
    } else if (item.sellerActiveCount != null) {
      bits.push(`${item.sellerActiveCount} annunci attivi`);
    }
    stats.push({
      label: p?.motivated ? "Venditore · 🎯 motivato" : "Venditore",
      value: label,
      hint: bits.length ? bits.join(" · ") : undefined,
      color: p?.motivated ? "oklch(0.75 0.15 150)" : undefined,
    });
  }
  if (item.repair) {
    stats.push({
      label: "Margine netto post-riparazione",
      value:
        item.repair.netMarginEur !== null
          ? `+${eur(item.repair.netMarginEur)}` +
            (item.repair.netMarginPct !== null ? ` (${item.repair.netMarginPct}%)` : "")
          : "—",
      hint: `solo ricambio Apple ${eur(item.repair.total)} · no manodopera`,
      color: "oklch(0.80 0.13 75)",
    });
  }
  if (props.category === "automobile" && item.expectedPrice !== null) {
    stats.push({
      label: "Prezzo atteso per questi km",
      value: eur(item.expectedPrice),
      hint:
        item.marginVsExpected !== null
          ? `${item.marginVsExpected >= 0 ? "+" : ""}${eur(item.marginVsExpected)} vs richiesto`
          : undefined,
      color: "var(--accent-text)",
    });
  }

  return (
    <div
      style={{
        background: "oklch(0.16 0.008 250)",
        border: "1px solid var(--accent-border)",
        borderRadius: "10px",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
        <div style={{ fontSize: "13px", fontWeight: 700, color: "var(--accent-text)" }}>
          🤝 Assistente trattativa
        </div>
        <div
          onClick={(e) => {
            e.stopPropagation();
            if (!props.inPipeline) props.onAddToPipeline();
          }}
          style={{
            padding: "7px 14px",
            borderRadius: "8px",
            fontSize: "12.5px",
            fontWeight: 700,
            cursor: props.inPipeline ? "default" : "pointer",
            background: props.inPipeline ? "oklch(0.24 0.008 250)" : "var(--accent)",
            color: props.inPipeline ? "oklch(0.62 0.01 250)" : "oklch(0.12 0.008 250)",
          }}
        >
          {props.inPipeline ? "✓ In pipeline" : "+ Aggiungi a pipeline"}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "10px",
        }}
      >
        {stats.map((s) => (
          <div
            key={s.label}
            style={{
              background: "oklch(0.19 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "8px",
              padding: "10px 12px",
            }}
          >
            <div style={{ fontSize: "10.5px", color: "oklch(0.46 0.01 250)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              {s.label}
            </div>
            <div style={{ fontFamily: MONO, fontSize: "15px", fontWeight: 700, marginTop: "3px", color: s.color ?? "oklch(0.94 0.004 250)" }}>
              {s.value}
            </div>
            {s.hint && (
              <div style={{ fontSize: "10.5px", color: "oklch(0.46 0.01 250)", marginTop: "2px" }}>{s.hint}</div>
            )}
          </div>
        ))}
      </div>

      {item.ai && (
        <div
          style={{
            background: "oklch(0.16 0.008 250)",
            border: "1px solid oklch(0.27 0.01 250)",
            borderRadius: "8px",
            padding: "10px 12px",
            fontSize: "12.5px",
            color: "oklch(0.82 0.008 250)",
            lineHeight: 1.5,
          }}
        >
          <div style={{ fontSize: "11px", fontWeight: 700, color: "oklch(0.70 0.13 300)", marginBottom: "4px" }}>
            🤖 Analisi AI
          </div>
          {item.ai.sintesi && <div>{item.ai.sintesi}</div>}
          <div style={{ marginTop: "4px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {item.ai.motivo_prezzo && (
              <span style={{ fontSize: "11px", padding: "2px 8px", borderRadius: "5px", background: "oklch(0.24 0.008 250)" }}>
                Motivo: {item.ai.motivo_prezzo}
                {item.ai.categoria_motivo && item.ai.categoria_motivo !== "nessuno"
                  ? ` (${item.ai.categoria_motivo})`
                  : ""}
              </span>
            )}
            {item.ai.riparabile && (
              <span style={{ fontSize: "11px", padding: "2px 8px", borderRadius: "5px", background: "oklch(0.75 0.14 75 / 0.16)", color: "oklch(0.80 0.13 75)" }}>
                🔧 riparabile{item.ai.nota_riparazione ? `: ${item.ai.nota_riparazione}` : ""}
              </span>
            )}
            {item.ai.rischio_truffa === "alto" && (
              <span style={{ fontSize: "11px", padding: "2px 8px", borderRadius: "5px", background: "oklch(0.68 0.19 25 / 0.16)", color: "oklch(0.75 0.16 30)" }}>
                ⚠️ rischio truffa alto
              </span>
            )}
          </div>
        </div>
      )}

      {item.scoreBreakdown.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {item.scoreBreakdown.map((b) => (
            <div
              key={b.label}
              style={{
                fontSize: "11px",
                padding: "2px 8px",
                borderRadius: "5px",
                background: b.points >= 0 ? "oklch(0.72 0.16 150 / 0.12)" : "oklch(0.68 0.19 25 / 0.12)",
                color: b.points >= 0 ? "oklch(0.75 0.14 150)" : "oklch(0.72 0.16 30)",
                fontWeight: 600,
              }}
            >
              {b.label} {b.points >= 0 ? "+" : ""}
              {b.points}
            </div>
          ))}
        </div>
      )}

      {(item.defects.length > 0 || item.features.length > 0) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {item.features.map((f) => (
            <span key={f} style={{ fontSize: "11px", padding: "2px 8px", borderRadius: "5px", background: "oklch(0.24 0.008 250)", color: "oklch(0.78 0.01 250)" }}>
              ✓ {f}
            </span>
          ))}
          {item.defects.map((d) => (
            <span key={d} style={{ fontSize: "11px", padding: "2px 8px", borderRadius: "5px", background: "oklch(0.68 0.19 25 / 0.12)", color: "oklch(0.75 0.14 30)" }}>
              ✕ {d}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- PIPELINE */

const STAGES: { key: DealStage; label: string }[] = [
  { key: "interessante", label: "Interessante" },
  { key: "contattato", label: "Contattato" },
  { key: "offerta", label: "Offerta" },
  { key: "comprato", label: "Comprato" },
  { key: "in_vendita", label: "In vendita" },
  { key: "venduto", label: "Venduto" },
  { key: "sfumato", label: "Sfumato" },
];

function PipelineScreen(props: {
  deals: Deal[];
  summary: DealsSummary | null;
  onUpdate: (
    id: string,
    patch: Partial<Pick<Deal, "stage" | "buy_price" | "sell_price">>,
  ) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const { deals, summary } = props;

  const card: CSSProperties = {
    background: "oklch(0.19 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "18px 20px",
  };
  const cardLabel: CSSProperties = {
    fontSize: "12px",
    color: "oklch(0.46 0.01 250)",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  };
  const cardValue: CSSProperties = { fontFamily: MONO, fontSize: "26px", fontWeight: 700, marginTop: "8px" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.2s ease" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Pipeline P&amp;L</div>
        <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
          Dal feed alla rivendita: profitto netto reale di ogni affare
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
        <div style={card}>
          <div style={cardLabel}>Profitto realizzato</div>
          <div style={{ ...cardValue, color: "oklch(0.72 0.16 150)" }}>
            {summary ? eur(summary.realizedProfit) : "—"}
          </div>
        </div>
        <div style={card}>
          <div style={cardLabel}>Capitale in gioco</div>
          <div style={cardValue}>{summary ? eur(summary.investedOpen) : "—"}</div>
        </div>
        <div style={card}>
          <div style={cardLabel}>Margine reale medio</div>
          <div style={cardValue}>
            {summary?.avgRealMarginPct != null ? `${summary.avgRealMarginPct}%` : "—"}
          </div>
        </div>
        <div style={card}>
          <div style={cardLabel}>Affari · venduti</div>
          <div style={cardValue}>
            {summary ? `${summary.totalDeals} · ${summary.sold}` : "—"}
          </div>
        </div>
      </div>

      {summary && summary.sold > 0 && summary.estimationAccuracyPct != null && (
        <div
          style={{
            background: "oklch(0.185 0.008 250)",
            border: "1px solid oklch(0.27 0.01 250)",
            borderRadius: "12px",
            padding: "16px 20px",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          <div style={{ fontSize: "14px", fontWeight: 700 }}>
            Feedback loop — quanto è affidabile il bot
          </div>
          <div style={{ display: "flex", gap: "28px", flexWrap: "wrap", fontFamily: MONO }}>
            <div>
              <div style={cardLabel}>Accuratezza stime</div>
              <div
                style={{
                  fontSize: "20px", fontWeight: 700, marginTop: "6px",
                  color:
                    summary.estimationAccuracyPct >= 75
                      ? "oklch(0.72 0.16 150)"
                      : summary.estimationAccuracyPct >= 50
                        ? "oklch(0.78 0.14 85)"
                        : "oklch(0.70 0.16 30)",
                }}
              >
                {summary.estimationAccuracyPct}%
              </div>
            </div>
            <div>
              <div style={cardLabel}>Scarto medio (reale − stima)</div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px",
                color: (summary.estimationBiasEur ?? 0) >= 0 ? "oklch(0.72 0.16 150)" : "oklch(0.70 0.16 30)" }}>
                {summary.estimationBiasEur != null
                  ? (summary.estimationBiasEur >= 0 ? "+" : "") + eur(summary.estimationBiasEur)
                  : "—"}
                <span style={{ fontSize: "11px", color: "oklch(0.55 0.01 250)", marginLeft: "6px" }}>
                  {(summary.estimationBiasEur ?? 0) >= 0 ? "sottostima" : "sovrastima"}
                </span>
              </div>
            </div>
            <div>
              <div style={cardLabel}>Stima → reale (medio)</div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {summary.avgEstimatedMarginEur != null ? eur(summary.avgEstimatedMarginEur) : "—"}
                {" → "}
                {summary.avgRealizedProfitEur != null ? eur(summary.avgRealizedProfitEur) : "—"}
              </div>
            </div>
            <div>
              <div style={cardLabel}>ROI/giorno realizzato</div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px", color: "oklch(0.78 0.14 195)" }}>
                {summary.realizedRoiPerDayPct != null ? `${summary.realizedRoiPerDayPct}%/gg` : "—"}
                {summary.avgHeldDays != null && (
                  <span style={{ fontSize: "11px", color: "oklch(0.55 0.01 250)", marginLeft: "6px" }}>
                    ~{summary.avgHeldDays}gg in stock
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {deals.length === 0 ? (
        <div
          style={{
            padding: "50px 20px",
            border: "1px dashed oklch(0.32 0.01 250)",
            borderRadius: "12px",
            textAlign: "center",
            color: "oklch(0.62 0.01 250)",
            fontSize: "13.5px",
          }}
        >
          Nessun affare in pipeline. Espandi un&apos;opportunità nel Live Sniper e premi
          «Aggiungi a pipeline».
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px", overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "2.2fr 1.3fr 1fr 1fr 1fr 40px",
              gap: "12px",
              padding: "10px 16px",
              background: "oklch(0.20 0.008 250)",
              fontSize: "11px",
              fontWeight: 600,
              color: "oklch(0.46 0.01 250)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            <div>Affare</div>
            <div>Stato</div>
            <div>Comprato</div>
            <div>Venduto</div>
            <div>Profitto</div>
            <div />
          </div>
          {deals.map((deal) => (
            <PipelineRow key={deal.id} deal={deal} onUpdate={props.onUpdate} onDelete={props.onDelete} />
          ))}
        </div>
      )}
    </div>
  );
}

function PipelineRow(props: {
  deal: Deal;
  onUpdate: (
    id: string,
    patch: Partial<Pick<Deal, "stage" | "buy_price" | "sell_price">>,
  ) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const { deal } = props;

  const numberCell = (
    value: number | null,
    onCommit: (v: number | null) => void,
    placeholder: string,
  ) => (
    <input
      defaultValue={value ?? ""}
      placeholder={placeholder}
      inputMode="numeric"
      onBlur={(e) => {
        const raw = e.target.value.trim();
        const num = raw === "" ? null : Number(raw.replace(/[^\d.]/g, ""));
        if (num !== value) onCommit(Number.isNaN(num as number) ? null : num);
      }}
      style={{
        width: "100%",
        height: "32px",
        background: "oklch(0.16 0.008 250)",
        border: "1px solid oklch(0.30 0.01 250)",
        borderRadius: "6px",
        padding: "0 8px",
        color: "oklch(0.94 0.004 250)",
        fontFamily: MONO,
        fontSize: "12.5px",
      }}
    />
  );

  const profitColor =
    deal.profit == null
      ? "oklch(0.46 0.01 250)"
      : deal.profit >= 0
        ? "oklch(0.72 0.16 150)"
        : "oklch(0.68 0.19 25)";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "2.2fr 1.3fr 1fr 1fr 1fr 40px",
        gap: "12px",
        padding: "12px 16px",
        alignItems: "center",
        borderTop: "1px solid oklch(0.24 0.008 250)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "13px", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {deal.title ?? "—"}
        </div>
        <div style={{ fontSize: "11px", color: "oklch(0.46 0.01 250)", fontFamily: MONO }}>
          {deal.category === "automobile" ? "🚗" : "📱"}{" "}
          {deal.estimatedMarginEur != null ? `stima +${eur(deal.estimatedMarginEur)}` : ""}
          {deal.listing_url && (
            <>
              {" · "}
              <a href={deal.listing_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent-text)", textDecoration: "none" }}>
                annuncio →
              </a>
            </>
          )}
        </div>
      </div>
      <select
        value={deal.stage}
        onChange={(e) => props.onUpdate(deal.id, { stage: e.target.value as DealStage })}
        style={{
          height: "32px",
          background: "oklch(0.16 0.008 250)",
          border: "1px solid oklch(0.30 0.01 250)",
          borderRadius: "6px",
          color: "oklch(0.94 0.004 250)",
          fontSize: "12.5px",
          padding: "0 6px",
        }}
      >
        {STAGES.map((s) => (
          <option key={s.key} value={s.key}>
            {s.label}
          </option>
        ))}
      </select>
      {numberCell(deal.buy_price, (v) => props.onUpdate(deal.id, { buy_price: v ?? undefined }), "€ pagato")}
      {numberCell(deal.sell_price, (v) => props.onUpdate(deal.id, { sell_price: v ?? undefined }), "€ venduto")}
      <div style={{ fontFamily: MONO, fontSize: "14px", fontWeight: 700, color: profitColor }}>
        {deal.profit != null ? (deal.profit >= 0 ? "+" : "") + eur(deal.profit) : "—"}
        {deal.realMarginPct != null && (
          <div style={{ fontSize: "10.5px", fontWeight: 600 }}>{deal.realMarginPct}%</div>
        )}
      </div>
      <div
        onClick={() => props.onDelete(deal.id)}
        title="Elimina"
        style={{
          width: "28px",
          height: "28px",
          borderRadius: "6px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          color: "oklch(0.55 0.01 250)",
          fontSize: "16px",
        }}
      >
        ×
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ INTEL */

function IntelScreen(props: {
  loading: boolean;
  error: string | null;
  intel: ApiTrends | null;
  trendPaths: { linePath: string; areaPath: string; min: number; max: number } | null;
  batchLastRun: string;
}) {
  const { intel, trendPaths } = props;
  const gradientId = "grad-trend";

  const card: CSSProperties = {
    background: "oklch(0.19 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "18px 20px",
  };
  const cardLabel: CSSProperties = {
    fontSize: "12px",
    color: "oklch(0.46 0.01 250)",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  };
  const cardValue: CSSProperties = { fontFamily: MONO, fontSize: "30px", fontWeight: 700, marginTop: "8px" };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.2s ease" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Market Intelligence</div>
        <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
          Computed nightly from the full classifieds corpus · last batch {props.batchLastRun}
        </div>
      </div>

      {props.error ? (
        <ErrorBanner message={props.error} />
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
            <div style={card}>
              <div style={cardLabel}>Annunci attivi</div>
              <div style={cardValue}>{props.loading ? "…" : (intel?.activeListings ?? 0)}</div>
              <div style={{ fontSize: "12px", color: "oklch(0.72 0.16 150)", marginTop: "4px", fontWeight: 600 }}>
                tracciati in questo verticale
              </div>
            </div>
            <div style={card}>
              <div style={cardLabel}>Prezzo medio di mercato</div>
              <div style={cardValue}>
                {props.loading ? "…" : intel?.avgMarketPrice != null ? eur(intel.avgMarketPrice) : "—"}
              </div>
              <div style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)", marginTop: "4px" }}>
                mediana dei prezzi attivi per modello
              </div>
            </div>
            <div style={card}>
              <div style={cardLabel}>Rotazione media</div>
              <div style={cardValue}>
                {props.loading
                  ? "…"
                  : intel?.avgDaysToSell != null
                    ? `${intel.avgDaysToSell}gg`
                    : "—"}
              </div>
              <div style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)", marginTop: "4px" }}>
                giorni medi di vendita (dai venduti)
              </div>
            </div>
            <div style={card}>
              <div style={cardLabel}>Miglior opportunità</div>
              <div style={{ ...cardValue, fontSize: "20px", color: "oklch(0.75 0.15 150)" }}>
                {props.loading ? "…" : (intel?.topOpportunity ?? "—")}
              </div>
              <div style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)", marginTop: "4px" }}>
                miglior margine × liquidità ora
              </div>
            </div>
          </div>

          <div
            style={{
              background: "oklch(0.19 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "12px",
              padding: "22px",
            }}
          >
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "10px" }}>
              <div>
                <div style={{ fontSize: "14px", fontWeight: 700 }}>Price Trend</div>
                <div style={{ fontSize: "12.5px", color: "oklch(0.62 0.01 250)", marginTop: "2px" }}>
                  {intel?.trendProduct ?? "—"}
                </div>
              </div>
              {trendPaths && (
                <div
                  style={{
                    display: "flex",
                    gap: "16px",
                    fontFamily: MONO,
                    fontSize: "12px",
                    color: "oklch(0.46 0.01 250)",
                  }}
                >
                  <div>low {eur(trendPaths.min)}</div>
                  <div>high {eur(trendPaths.max)}</div>
                </div>
              )}
            </div>
            {trendPaths ? (
              <svg viewBox="0 0 600 200" style={{ width: "100%", height: "220px", display: "block" }}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d={trendPaths.areaPath} fill={`url(#${gradientId})`} stroke="none" />
                <path
                  d={trendPaths.linePath}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="2.5"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <div
                style={{
                  height: "220px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "oklch(0.46 0.01 250)",
                  fontSize: "13px",
                }}
              >
                {props.loading ? "Caricamento…" : "Servono almeno 2 batch notturni per tracciare il trend."}
              </div>
            )}
          </div>

          <BuyRanking models={intel?.models ?? []} loading={props.loading} />

          <SellerRanking sellers={intel?.sellers ?? []} />
        </>
      )}
    </div>
  );
}

function SellerRanking(props: { sellers: SellerRankRow[] }) {
  const { sellers } = props;
  if (sellers.length === 0) return null;
  const typeLabel = (t: string | null) =>
    t === "finto_privato" ? "⚠️ finto privato" : t === "dealer" ? "concessionario" : "privato";
  const header: CSSProperties = {
    fontSize: "11px", fontWeight: 600, color: "oklch(0.46 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.05em",
  };
  const cols = "1.8fr 1fr 0.7fr 0.7fr 0.9fr 0.9fr";
  return (
    <div>
      <div style={{ fontSize: "15px", fontWeight: 700, marginBottom: "4px" }}>Venditori</div>
      <div style={{ fontSize: "12.5px", color: "oklch(0.62 0.01 250)", marginBottom: "10px" }}>
        Chi è più attivo e più motivato (vende in fretta o ribassa spesso) — la priorità di contatto.
      </div>
      <div style={{ border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px", overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, gap: "10px", padding: "10px 16px", background: "oklch(0.20 0.008 250)", ...header }}>
          <div>Venditore</div>
          <div>Tipo</div>
          <div title="Annunci attivi">Attivi</div>
          <div title="Annunci venduti">Venduti</div>
          <div title="Giorni medi di vendita">Giorni</div>
          <div title="% annunci ribassati">Ribassa</div>
        </div>
        {sellers.map((s) => (
          <div
            key={s.sellerId}
            style={{
              display: "grid", gridTemplateColumns: cols, gap: "10px",
              padding: "11px 16px", alignItems: "center", fontSize: "13px",
              borderTop: "1px solid oklch(0.24 0.008 250)",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "7px" }}>
                {s.motivated && (
                  <span style={{ fontSize: "11px", color: "oklch(0.75 0.15 150)", fontWeight: 700 }}>🎯</span>
                )}
                <span style={{ fontFamily: MONO, fontSize: "12px", color: "oklch(0.6 0.01 250)" }}>
                  #{s.sellerId}
                </span>
              </div>
              {s.sampleTitle && (
                <div style={{ fontSize: "11.5px", color: "oklch(0.5 0.01 250)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {s.sampleTitle}
                </div>
              )}
            </div>
            <div style={{ fontSize: "12px", color: s.type === "finto_privato" ? "oklch(0.78 0.16 30)" : "oklch(0.7 0.01 250)" }}>
              {typeLabel(s.type)}
            </div>
            <div style={{ fontFamily: MONO }}>{s.active}</div>
            <div style={{ fontFamily: MONO }}>{s.sold || "—"}</div>
            <div style={{ fontFamily: MONO }}>{s.avgDaysToSell != null ? `${s.avgDaysToSell}gg` : "—"}</div>
            <div style={{ fontFamily: MONO, color: s.dropRate >= 40 ? "oklch(0.75 0.15 150)" : "oklch(0.7 0.01 250)" }}>
              {s.dropRate > 0 ? `${s.dropRate}%` : "—"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* -------------------------------- "Cosa comprare": ranking + dettaglio (#6) */

const BUY_COLS = "1.7fr 0.8fr 0.9fr 1fr 0.9fr 0.8fr 0.7fr 28px";

function BuyRanking(props: { models: ApiModelStat[]; loading: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const header: CSSProperties = {
    fontSize: "11px",
    fontWeight: 600,
    color: "oklch(0.46 0.01 250)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  };
  return (
    <div>
      <div style={{ fontSize: "15px", fontWeight: 700, marginBottom: "4px" }}>
        Cosa comprare
      </div>
      <div style={{ fontSize: "12.5px", color: "oklch(0.62 0.01 250)", marginBottom: "10px" }}>
        Modelli ordinati per ROI/giorno di capitale (margine ÷ giorni di vendita). Clicca una riga per il dettaglio.
      </div>
      <div style={{ border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px", overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: BUY_COLS,
            gap: "10px",
            padding: "10px 16px",
            background: "oklch(0.20 0.008 250)",
            ...header,
          }}
        >
          <div>Modello</div>
          <div title="ROI per giorno di capitale = margine ÷ giorni medi di vendita">ROI/gg</div>
          <div title="Mediana ↔ 10° percentile: quanto margine c'è">Margine pot.</div>
          <div title="Prezzo di vendita reale (mediana venduti)">Venduto</div>
          <div title="Giorni medi di vendita">Giorni</div>
          <div title="% annunci venduti su visti">Sell-thru</div>
          <div title="Annunci affare attivi ora / volume totale">Affari</div>
          <div />
        </div>
        {props.models.length === 0 ? (
          <div style={{ padding: "16px", fontSize: "13px", color: "oklch(0.46 0.01 250)" }}>
            {props.loading ? "Caricamento…" : "Nessun dato per questa categoria."}
          </div>
        ) : (
          props.models.map((m) => (
            <BuyRow
              key={m.name}
              m={m}
              open={open === m.name}
              onToggle={() => setOpen((cur) => (cur === m.name ? null : m.name))}
            />
          ))
        )}
      </div>
    </div>
  );
}

function BuyRow(props: { m: ApiModelStat; open: boolean; onToggle: () => void }) {
  const { m } = props;
  const roi = m.roiPerDayPct;
  const oppColor =
    roi != null && roi >= 1
      ? "oklch(0.75 0.15 150)"
      : roi != null && roi >= 0.4
        ? "oklch(0.75 0.14 75)"
        : "oklch(0.62 0.01 250)";
  return (
    <div style={{ borderTop: "1px solid oklch(0.24 0.008 250)" }}>
      <div
        onClick={props.onToggle}
        style={{
          display: "grid",
          gridTemplateColumns: BUY_COLS,
          gap: "10px",
          padding: "12px 16px",
          alignItems: "center",
          fontSize: "13px",
          cursor: "pointer",
          background: props.open ? "oklch(0.22 0.008 250)" : "transparent",
        }}
      >
        <div style={{ fontWeight: 600 }}>{m.name}</div>
        <div style={{ fontFamily: MONO, fontWeight: 700, color: oppColor }}>
          {roi != null ? `${roi}%` : "—"}
        </div>
        <div style={{ fontFamily: MONO }}>
          {m.marginPotentialPct != null ? `${m.marginPotentialPct}%` : "—"}
        </div>
        <div style={{ fontFamily: MONO }}>
          {m.soldMedian != null ? (
            eur(m.soldMedian)
          ) : m.medianActive != null ? (
            <span style={{ color: "oklch(0.55 0.01 250)" }} title="mediana listati (no venduti)">
              {eur(m.medianActive)}
            </span>
          ) : (
            "—"
          )}
        </div>
        <div style={{ fontFamily: MONO }}>
          {m.avgDaysToSell != null ? `${m.avgDaysToSell}gg` : "—"}
        </div>
        <div style={{ fontFamily: MONO }}>
          {m.sellThroughRate != null ? `${m.sellThroughRate}%` : "—"}
        </div>
        <div style={{ fontFamily: MONO }}>
          <span style={{ color: m.activeDeals > 0 ? "oklch(0.75 0.15 150)" : "oklch(0.62 0.01 250)" }}>
            {m.activeDeals}
          </span>
          <span style={{ color: "oklch(0.46 0.01 250)" }}>/{m.volume}</span>
        </div>
        <div style={{ color: "oklch(0.55 0.01 250)", textAlign: "center" }}>
          {props.open ? "▾" : "▸"}
        </div>
      </div>
      {props.open && <BuyDetail m={m} />}
    </div>
  );
}

function BuyDetail(props: { m: ApiModelStat }) {
  const { m } = props;
  const block: CSSProperties = {
    background: "oklch(0.16 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "8px",
    padding: "12px 14px",
  };
  const blkLabel: CSSProperties = {
    fontSize: "10.5px",
    fontWeight: 700,
    color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    marginBottom: "8px",
  };
  const storages = Object.entries(m.storagePremium).sort((a, b) => Number(a[0]) - Number(b[0]));
  const conds = Object.entries(m.conditionImpact);
  const ai = m.ai;
  return (
    <div
      style={{
        padding: "0 16px 16px",
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: "12px",
        background: "oklch(0.185 0.008 250)",
      }}
    >
      {/* Box prezzi */}
      {m.priceBox && (
        <div style={block}>
          <div style={blkLabel}>Distribuzione prezzi attivi</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            <div>min {eur(m.priceBox.min)} · max {eur(m.priceBox.max)}</div>
            <div>25° {eur(m.priceBox.q1)} · mediana <b>{eur(m.priceBox.median)}</b> · 75° {eur(m.priceBox.q3)}</div>
            {m.spreadEur != null && (
              <div style={{ color: "oklch(0.75 0.15 150)" }}>
                spread affare ~{eur(m.spreadEur)} ({m.marginPotentialPct}%)
              </div>
            )}
          </div>
        </div>
      )}

      {/* Domanda / offerta (ultimi 7 giorni) */}
      {(m.inflow7d > 0 || m.outflow7d > 0) && (
        <div style={block}>
          <div style={blkLabel}>Domanda / offerta (7gg)</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            <div>nuovi immessi: {m.inflow7d}</div>
            <div>venduti: {m.outflow7d}</div>
            {m.demandIndex != null && (
              <div
                style={{
                  color:
                    m.demandIndex >= 1
                      ? "oklch(0.75 0.15 150)"
                      : m.demandIndex >= 0.5
                        ? "oklch(0.75 0.14 75)"
                        : "oklch(0.70 0.16 30)",
                }}
                title="venduti ÷ nuovi immessi: >1 = si vende più in fretta di quanto entra offerta (prezzi in salita)"
              >
                indice domanda ×{m.demandIndex}{" "}
                {m.demandIndex >= 1 ? "↑ comprare" : m.demandIndex >= 0.5 ? "→ stabile" : "↓ saturo"}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Momentum prezzo (trend storico) */}
      {m.changePct != null && (
        <div style={block}>
          <div style={blkLabel}>Momentum prezzo</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            {m.avg != null && <div>media attuale {eur(m.avg)}</div>}
            <div
              style={{
                color:
                  m.changePct <= -3
                    ? "oklch(0.72 0.16 150)"
                    : m.changePct >= 3
                      ? "oklch(0.70 0.16 30)"
                      : "oklch(0.62 0.01 250)",
              }}
              title="Variazione della media di mercato sullo storico (market_trends)"
            >
              {m.changePct >= 0 ? "+" : ""}
              {m.changePct}% sullo storico{" "}
              {m.changePct <= -3 ? "↓ in calo (compra)" : m.changePct >= 3 ? "↑ in salita" : "→ stabile"}
            </div>
          </div>
        </div>
      )}

      {/* Premio memoria */}
      {storages.length > 0 && (
        <div style={block}>
          <div style={blkLabel}>Premio memoria (mediana)</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            {storages.map(([st, price]) => (
              <div key={st}>
                {Number(st) >= 1024 ? "1TB" : `${st}GB`}: {eur(price)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Impatto condizione */}
      {conds.length > 0 && (
        <div style={block}>
          <div style={blkLabel}>Impatto condizione (mediana)</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            {conds.map(([tier, price]) => (
              <div key={tier}>
                {tier}: {eur(price)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Prezzo → giorni */}
      {m.priceBands.length > 0 && (
        <div style={block}>
          <div style={blkLabel}>Prezzo → giorni di vendita</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            {m.priceBands.map((b) => (
              <div key={b.band}>
                {b.band} {eur(b.priceFrom)}–{eur(b.priceTo)}: <b>{b.avgDays}gg</b> ({b.count})
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI motivi */}
      {ai.analyzed > 0 && (
        <div style={block}>
          <div style={blkLabel}>🤖 Motivi di vendita (AI, {ai.analyzed})</div>
          <div style={{ fontSize: "12px", lineHeight: 1.7 }}>
            <div>legittimi: {ai.legittimo} · difetti: {ai.difetto} · sospetti: {ai.sospetto}</div>
            <div style={{ color: "oklch(0.80 0.13 75)" }}>riparabili: {ai.riparabili}</div>
          </div>
        </div>
      )}

      {/* Venditori */}
      <div style={block}>
        <div style={blkLabel}>Venditori</div>
        <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
          <div>distinti: {m.sellers}</div>
          {m.fintoPrivato > 0 && (
            <div style={{ color: "oklch(0.75 0.16 30)" }}>finti privati: {m.fintoPrivato}</div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ AUTOMATIONS */

const JOB_ICON: Record<string, string> = {
  sniper_live: "🎯",
  sniper_auto_live: "🎯",
  nightly_batch: "🌙",
  garbage_collector: "🧹",
  ai_enrich: "🤖",
};

const JOB_INTERVALS = [5, 10, 15, 30, 60];

function fmtNextRun(job: AutomationJob): string {
  if (job.paused || !job.nextRun) return "in pausa";
  const diff = new Date(job.nextRun).getTime() - Date.now();
  if (diff <= 0) return "a breve";
  const m = Math.floor(diff / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  if (m >= 60) return `tra ${Math.floor(m / 60)}h ${m % 60}m`;
  if (m > 0) return `tra ${m}m`;
  return `tra ${s}s`;
}

/* ---------------------------------------------------------- Impostazioni */

const PART_LABEL: Record<string, string> = {
  "schermo-rotto": "Schermo",
  "batteria-esausta": "Batteria",
};
const TIER_LABEL: Record<string, string> = {
  base: "Base", plus: "Plus", pro: "Pro", "pro-max": "Pro Max",
};

function SettingsScreen() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    fetchSettings(c.signal).then(setS).catch(() => setS(null));
    return () => c.abort();
  }, []);

  const save = async () => {
    if (!s) return;
    setSaving(true);
    setMsg(null);
    try {
      const upd = await updateSettings(s);
      setS(upd);
      setMsg("Salvato ✓");
    } catch {
      setMsg("Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  };

  if (!s) {
    return (
      <div style={{ color: "oklch(0.6 0.01 250)", fontSize: "14px" }}>
        Caricamento impostazioni… (verifica che il backend sia attivo)
      </div>
    );
  }

  const card: CSSProperties = {
    background: "oklch(0.185 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "18px 20px",
    display: "flex",
    flexDirection: "column",
    gap: "14px",
  };
  const label: CSSProperties = {
    fontSize: "10.5px", fontWeight: 700, color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: "6px",
  };
  const num = (value: number, onChange: (v: number) => void, suffix?: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          width: "90px", height: "34px", background: "oklch(0.20 0.008 250)",
          border: "1px solid oklch(0.32 0.01 250)", borderRadius: "8px",
          padding: "0 10px", color: "oklch(0.94 0.004 250)", fontFamily: MONO,
          fontSize: "13px",
        }}
      />
      {suffix && <span style={{ fontSize: "12px", color: "oklch(0.55 0.01 250)" }}>{suffix}</span>}
    </div>
  );
  const field = (title: string, node: ReactNode) => (
    <div>
      <div style={label}>{title}</div>
      {node}
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", maxWidth: "760px", animation: "fadeIn 0.2s ease" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Impostazioni</div>
        <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
          Parametri di business, senza toccare il codice. Salva per applicare (vale
          dai prossimi calcoli e giri sniper).
        </div>
      </div>

      {/* Soglie alert */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Soglie alert Telegram</div>
        <div style={{ display: "flex", gap: "24px", flexWrap: "wrap" }}>
          {field("Deal Score minimo", num(s.alert_min_score, (v) => setS({ ...s, alert_min_score: v })))}
          {field("Margine minimo", num(s.alert_min_margin_pct, (v) => setS({ ...s, alert_min_margin_pct: v }), "%"))}
          {field("Calo prezzo minimo", num(s.alert_min_drop_pct, (v) => setS({ ...s, alert_min_drop_pct: v }), "%"))}
        </div>
      </div>

      {/* Margine obiettivo */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Margine obiettivo (per max bid e offerta)</div>
        <div style={{ display: "flex", gap: "24px", flexWrap: "wrap" }}>
          {Object.entries(s.target_margin_pct).map(([cat, v]) =>
            field(
              cat === "smartphone" ? "iPhone" : "Auto",
              num(v, (nv) => setS({ ...s, target_margin_pct: { ...s.target_margin_pct, [cat]: nv } }), "%"),
            ),
          )}
        </div>
      </div>

      {/* Ricambi Apple */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Prezzi ricambi Apple (solo pezzo, no manodopera)</div>
        <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "-6px" }}>
          Inserisci i prezzi esatti del ricambio dal sito Apple (Self Service Repair).
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "90px 1fr 1fr", gap: "10px", alignItems: "center" }}>
          <div />
          <div style={label}>Schermo</div>
          <div style={label}>Batteria</div>
          {Object.entries(s.apple_part_eur).map(([tier, parts]) => (
            <Fragment key={tier}>
              <div style={{ fontSize: "13px", fontWeight: 600 }}>{TIER_LABEL[tier] ?? tier}</div>
              {["schermo-rotto", "batteria-esausta"].map((pk) => (
                <div key={pk}>
                  {num(parts[pk] ?? 0, (nv) =>
                    setS({
                      ...s,
                      apple_part_eur: {
                        ...s.apple_part_eur,
                        [tier]: { ...parts, [pk]: nv },
                      },
                    }),
                    "€",
                  )}
                </div>
              ))}
            </Fragment>
          ))}
        </div>
      </div>

      {/* Telegram chat */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Chat Telegram</div>
        <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "-6px" }}>
          Il token del bot resta in <span style={{ fontFamily: MONO }}>.env</span>. Qui gli ID chat di destinazione.
        </div>
        <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
          {([
            ["telegram_chat_tech", "iPhone"],
            ["telegram_chat_auto", "Auto"],
            ["telegram_chat_ops", "Sistema"],
          ] as [keyof AppSettings, string][]).map(([k, lab]) =>
            field(
              lab,
              <input
                value={(s[k] as string | null) ?? ""}
                onChange={(e) => setS({ ...s, [k]: e.target.value || null })}
                placeholder="chat id"
                style={{
                  width: "150px", height: "34px", background: "oklch(0.20 0.008 250)",
                  border: "1px solid oklch(0.32 0.01 250)", borderRadius: "8px",
                  padding: "0 10px", color: "oklch(0.94 0.004 250)", fontFamily: MONO,
                  fontSize: "13px",
                }}
              />,
            ),
          )}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
        <div
          onClick={saving ? undefined : save}
          style={{
            padding: "10px 22px", borderRadius: "9px", fontSize: "14px", fontWeight: 700,
            cursor: saving ? "default" : "pointer",
            background: "var(--accent)", color: "oklch(0.12 0.008 250)",
            opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? "Salvataggio…" : "Salva impostazioni"}
        </div>
        {msg && <span style={{ fontSize: "13px", color: "oklch(0.75 0.15 150)" }}>{msg}</span>}
      </div>
    </div>
  );
}

const HEALTH_COLOR: Record<string, string> = {
  ok: "oklch(0.72 0.16 150)",
  degraded: "oklch(0.78 0.14 85)",
  down: "oklch(0.68 0.19 25)",
  idle: "oklch(0.55 0.01 250)",
};
const HEALTH_LABEL: Record<string, string> = {
  ok: "Operativo", degraded: "Degradato", down: "Bloccato", idle: "Inattivo",
};

function ScraperHealthPanel(props: { health: ScraperHealth }) {
  const { health } = props;
  const cats: [string, string][] = [
    ["smartphone", "iPhone"],
    ["automobile", "Auto"],
  ];
  const box: CSSProperties = {
    background: "oklch(0.185 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "16px 18px",
    flex: "1 1 300px",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  };
  const lab: CSSProperties = {
    fontSize: "10.5px", fontWeight: 700, color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.04em",
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      <div style={{ display: "flex", gap: "14px", flexWrap: "wrap" }}>
        {cats.map(([cat, label]) => {
          const last = health.scraper[cat];
          const cov = health.coverage[cat];
          const recent = health.recent[cat] ?? [];
          const status = last?.status ?? "idle";
          return (
            <div key={cat} style={box}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ fontSize: "15px", fontWeight: 700 }}>{label}</div>
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: "6px",
                    padding: "3px 10px", borderRadius: "20px",
                    background: "oklch(0.24 0.008 250)",
                  }}
                >
                  <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: HEALTH_COLOR[status] }} />
                  <span style={{ fontSize: "11.5px", fontWeight: 700, color: HEALTH_COLOR[status] }}>
                    {HEALTH_LABEL[status] ?? status}
                  </span>
                </div>
              </div>
              <div style={{ display: "flex", gap: "18px", flexWrap: "wrap", fontFamily: MONO }}>
                <div>
                  <div style={lab}>Target attivi</div>
                  <div style={{ fontSize: "17px", fontWeight: 700 }}>{cov?.activeTargets ?? "—"}</div>
                </div>
                <div>
                  <div style={lab}>In magazzino</div>
                  <div style={{ fontSize: "17px", fontWeight: 700 }}>{cov?.activeListings ?? "—"}</div>
                </div>
                <div>
                  <div style={lab}>Nuovi / 24h</div>
                  <div style={{ fontSize: "17px", fontWeight: 700, color: "oklch(0.78 0.14 195)" }}>
                    {cov?.new24h ?? "—"}
                  </div>
                </div>
              </div>
              {/* Mini timeline degli ultimi giri (più recente a destra) */}
              <div style={{ display: "flex", gap: "3px", alignItems: "center" }}>
                {[...recent].reverse().map((r, i) => (
                  <span
                    key={i}
                    title={`${r.status} · ${relativeTime(r.ran_at)} · ${r.new_count} nuovi`}
                    style={{
                      width: "10px", height: "10px", borderRadius: "3px",
                      background: HEALTH_COLOR[r.status] ?? "gray",
                    }}
                  />
                ))}
                {recent.length === 0 && (
                  <span style={{ fontSize: "11.5px", color: "oklch(0.5 0.01 250)" }}>
                    nessun giro registrato ancora
                  </span>
                )}
              </div>
              {last?.ran_at && (
                <div style={{ fontSize: "11.5px", color: "oklch(0.5 0.01 250)" }}>
                  ultimo giro {relativeTime(last.ran_at)} · {last.ok}/{last.targets} target ok · {last.scraped} annunci
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: "12px", color: "oklch(0.55 0.01 250)" }}>
        Proxy residenziale {health.proxy_configured ? "✓ configurato" : "✗ non configurato (connessione diretta)"} ·
        impronte TLS: {health.impersonate_pool?.join(", ") || "—"}
      </div>
    </div>
  );
}

function AutomationsScreen() {
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [health, setHealth] = useState<ScraperHealth | null>(null);

  const reload = useCallback(async (signal?: AbortSignal) => {
    try {
      const [state, h] = await Promise.all([
        fetchAutomations(signal),
        fetchScraperHealth(signal).catch(() => null),
      ]);
      setJobs(state.jobs);
      setRunning(state.running);
      setHealth(h);
      setErr(null);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setErr("Backend non raggiungibile");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    // microtask: evita il setState sincrono nel corpo dell'effect.
    Promise.resolve().then(() => reload(ctrl.signal));
    const poll = setInterval(() => reload(), 15000);
    return () => {
      ctrl.abort();
      clearInterval(poll);
    };
  }, [reload]);

  const act = async (id: string, fn: () => Promise<AutomationJob>) => {
    setBusy(id);
    try {
      await fn();
      await reload();
    } catch {
      setErr("Azione non riuscita");
    } finally {
      setBusy(null);
    }
  };

  const panel: CSSProperties = {
    background: "oklch(0.19 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "20px",
    display: "flex",
    flexDirection: "column",
    gap: "14px",
  };
  const btn = (accent: boolean): CSSProperties => ({
    padding: "8px 14px",
    borderRadius: "7px",
    fontSize: "12.5px",
    fontWeight: 700,
    cursor: "pointer",
    userSelect: "none",
    background: accent ? "var(--accent)" : "oklch(0.24 0.008 250)",
    color: accent ? "oklch(0.12 0.008 250)" : "oklch(0.82 0.01 250)",
    border: "1px solid oklch(0.30 0.01 250)",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.2s ease" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: "22px", fontWeight: 700 }}>Automations &amp; Alerts</div>
          <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
            Controllo reale dei motori schedulati (avvio, pausa, cadenza)
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "7px",
            padding: "5px 12px",
            borderRadius: "20px",
            background: running ? "oklch(0.72 0.16 150 / 0.14)" : "oklch(0.68 0.19 25 / 0.14)",
          }}
        >
          <div
            style={{
              width: "7px",
              height: "7px",
              borderRadius: "50%",
              background: running ? "oklch(0.72 0.16 150)" : "oklch(0.68 0.19 25)",
              animation: running ? "pulseDot 2s ease-in-out infinite" : "none",
            }}
          />
          <div style={{ fontSize: "12px", fontWeight: 700, color: running ? "oklch(0.72 0.16 150)" : "oklch(0.68 0.19 25)" }}>
            Scheduler {running ? "attivo" : "fermo"}
          </div>
        </div>
      </div>

      {health && <ScraperHealthPanel health={health} />}

      {err && (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: "8px",
            background: "oklch(0.68 0.19 25 / 0.12)",
            border: "1px solid oklch(0.68 0.19 25 / 0.3)",
            color: "oklch(0.75 0.16 25)",
            fontSize: "13px",
          }}
        >
          {err}
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: "13px", color: "oklch(0.46 0.01 250)" }}>Caricamento…</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "16px" }}>
          {jobs.map((job) => {
            const isBusy = busy === job.id;
            return (
              <div key={job.id} style={{ ...panel, opacity: isBusy ? 0.6 : 1 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px" }}>
                  <div style={{ fontSize: "14.5px", fontWeight: 700 }}>
                    <span style={{ marginRight: "7px" }}>{JOB_ICON[job.id] ?? "⚙️"}</span>
                    {job.name}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      flexShrink: 0,
                      padding: "4px 10px",
                      borderRadius: "20px",
                      background: job.paused ? "oklch(0.46 0.01 250 / 0.16)" : "oklch(0.72 0.16 150 / 0.14)",
                    }}
                  >
                    <div
                      style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        background: job.paused ? "oklch(0.62 0.01 250)" : "oklch(0.72 0.16 150)",
                      }}
                    />
                    <div
                      style={{
                        fontFamily: MONO,
                        fontSize: "11.5px",
                        fontWeight: 700,
                        color: job.paused ? "oklch(0.62 0.01 250)" : "oklch(0.72 0.16 150)",
                      }}
                    >
                      {fmtNextRun(job)}
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: "12.5px", color: "oklch(0.55 0.01 250)" }}>
                  {job.kind === "interval" && job.intervalMinutes != null
                    ? `Ogni ${job.intervalMinutes} min`
                    : "Ogni giorno (orario fisso)"}
                  {job.category ? ` · ${job.category === "smartphone" ? "tech" : job.category}` : ""}
                </div>

                {job.kind === "interval" && (
                  <div>
                    <div style={{ fontSize: "11px", color: "oklch(0.46 0.01 250)", marginBottom: "6px" }}>
                      Cadenza
                    </div>
                    <div
                      style={{
                        display: "flex",
                        background: "oklch(0.16 0.008 250)",
                        border: "1px solid oklch(0.27 0.01 250)",
                        borderRadius: "8px",
                        padding: "3px",
                        gap: "2px",
                        width: "fit-content",
                      }}
                    >
                      {JOB_INTERVALS.map((min) => {
                        const active = job.intervalMinutes === min;
                        return (
                          <div
                            key={min}
                            onClick={() =>
                              !active && !isBusy && act(job.id, () => rescheduleAutomation(job.id, min))
                            }
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              fontSize: "12px",
                              fontWeight: 600,
                              cursor: active ? "default" : "pointer",
                              background: active ? "var(--accent)" : "transparent",
                              color: active ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
                            }}
                          >
                            {min >= 60 ? `${min / 60}h` : `${min}m`}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div style={{ display: "flex", gap: "8px", marginTop: "2px" }}>
                  <div
                    onClick={() => !isBusy && act(job.id, () => runAutomation(job.id))}
                    style={btn(true)}
                  >
                    ▶ Avvia ora
                  </div>
                  {job.paused ? (
                    <div
                      onClick={() => !isBusy && act(job.id, () => resumeAutomation(job.id))}
                      style={btn(false)}
                    >
                      Riprendi
                    </div>
                  ) : (
                    <div
                      onClick={() => !isBusy && act(job.id, () => pauseAutomation(job.id))}
                      style={btn(false)}
                    >
                      ⏸ Pausa
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div
        style={{
          ...panel,
          background: "oklch(0.17 0.008 250)",
          gap: "8px",
        }}
      >
        <div style={{ fontSize: "14px", fontWeight: 700 }}>📲 Alert Telegram intelligenti</div>
        <div style={{ fontSize: "12.5px", color: "oklch(0.62 0.01 250)", lineHeight: 1.6 }}>
          A ogni giro dello sniper vengono notificati solo i veri affari (classe
          «affare» + Deal Score sopra soglia, esclusi i sospetti), con valore
          equo, offerta consigliata, radar riparazioni e motivo AI. Più i cali di
          prezzo rilevanti sugli annunci già tracciati. Chat e soglie si
          configurano nel file <span style={{ fontFamily: MONO }}>.env</span> del
          backend (TELEGRAM_CHAT_ID_TECH/AUTO, ALERT_MIN_SCORE, ALERT_MIN_DROP_PCT).
        </div>
      </div>
    </div>
  );
}
