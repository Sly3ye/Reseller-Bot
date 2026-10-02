"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import {
  createDeal,
  deleteDeal,
  fetchAutomations,
  fetchDeals,
  fetchDealsSummary,
  fetchDepreciation,
  fetchOpportunities,
  fetchScraperHealth,
  fetchDataQuality,
  fetchRepairMatrix,
  fetchSettings,
  fetchTimeToSale,
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
  type DepreciationCurve,
  type DepreciationData,
  type DepreciationPoint,
  type OpportunityFacets,
  type PresetMode,
  type ScraperHealth,
  type DataQuality,
  type DealRepair,
  type RepairCell,
  type RepairMatrix,
  type TargetCoverage,
  type SellerRankRow,
  type SortMode,
  type TimeToSaleData,
  type TimeToSaleRecord,
  type ViewMode,
} from "@/lib/api";
import {
  dealClassStyle,
  eur,
  marginColor,
  marginTier,
  relativeTime,
  scoreColor,
  sellerTypeLabel,
} from "@/lib/flipradar-data";

const MONO = "var(--font-ibm-plex-mono), 'IBM Plex Mono', monospace";

type Vertical = "tech" | "auto";
type Screen = "sniper" | "riparazioni" | "intel" | "tempo" | "pipeline" | "automations" | "settings";
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
  const [fMinPrice, setFMinPrice] = useState<number | null>(null);
  const [fMaxPrice, setFMaxPrice] = useState<number | null>(null);
  const [fMinDays, setFMinDays] = useState<number | null>(null);
  const [fMaxDays, setFMaxDays] = useState<number | null>(null);
  // Guasto (dalla matrice Riparazioni): annunci con SOLO quel guasto.
  const [fDefect, setFDefect] = useState<{ code: string; label: string } | null>(null);
  const [page, setPage] = useState(0);

  const [opportunities, setOpportunities] = useState<ApiOpportunity[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<OpportunityFacets>(EMPTY_FACETS);
  const [intel, setIntel] = useState<ApiTrends | null>(null);
  const [depreciation, setDepreciation] = useState<DepreciationData | null>(null);
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
    fetchDepreciation(category, controller.signal)
      .then(setDepreciation)
      .catch(() => {
        if (!controller.signal.aborted) setDepreciation(null);
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
        minPrice: fMinPrice,
        maxPrice: fMaxPrice,
        minDays: fMinDays,
        maxDays: fMaxDays,
        q: search || null,
        view,
        preset,
        defect: fDefect?.code ?? null,
        onlyDefect: !!fDefect,
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
    fMinPrice, fMaxPrice, fMinDays, fMaxDays,
    marginFilter, search, view, preset, page, fDefect,
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
          // La stima di OGGI resta agganciata all'affare: il confronto con la
          // realtà non cambia se domani cambiano listini o prezzi di mercato.
          estimate: item.repair
            ? {
                kind: "riparazione",
                marginEur: item.repair.netMarginEur,
                repairItems: item.repair.items.map((r) => ({
                  part: r.part, source: r.source, cost: r.cost,
                  partCost: r.partCost ?? null,
                })),
                resaleAfterRepair: item.repair.resaleAfterRepair ?? null,
                maxBid: item.maxBid,
              }
            : {
                kind: "rivendita",
                marginEur:
                  item.marketAvg != null && item.askingPrice != null
                    ? item.marketAvg - item.askingPrice
                    : null,
                maxBid: item.maxBid,
              },
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
    setFDefect(null);
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

          {isTech && (
            <div onClick={() => setScreen("riparazioni")} style={navItem(screen === "riparazioni")}>
              <div
                style={{
                  width: "16px",
                  height: "16px",
                  flexShrink: 0,
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "2px",
                }}
              >
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} style={{ background: "currentColor", borderRadius: "1px", opacity: i === 1 ? 0.45 : 1 }} />
                ))}
              </div>
              Riparazioni
            </div>
          )}

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

          <div onClick={() => setScreen("tempo")} style={navItem(screen === "tempo")}>
            <div
              style={{
                width: "16px",
                height: "16px",
                borderRadius: "50%",
                border: "2px solid currentColor",
                position: "relative",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: "2px",
                  left: "6px",
                  width: "2px",
                  height: "5px",
                  background: "currentColor",
                }}
              />
              <div
                style={{
                  position: "absolute",
                  top: "6px",
                  left: "6px",
                  width: "5px",
                  height: "2px",
                  background: "currentColor",
                }}
              />
            </div>
            Tempo di vendita
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
          {screen === "riparazioni" && (
            <RepairMatrixScreen
              onOpenCell={(cell) => {
                setFModel(cell.modelKey);
                setFDefect({ code: cell.defect, label: `${cell.model} · ${cell.defectLabel}` });
                setPreset(null);
                setSortMode("margin");
                setPage(0);
                setScreen("sniper");
              }}
            />
          )}

          {screen === "sniper" && fDefect && (
            <div
              style={{
                display: "flex", alignItems: "center", gap: "10px", marginBottom: "14px",
                padding: "8px 12px", borderRadius: "10px", fontSize: "13px",
                background: "var(--accent-soft)", color: "var(--accent-text)", width: "fit-content",
              }}
            >
              🔧 Solo annunci con questo guasto: <b>{fDefect.label}</b>
              <span
                onClick={() => {
                  setFDefect(null);
                  setFModel(null);
                  setPage(0);
                }}
                style={{ cursor: "pointer", fontWeight: 700 }}
                title="Togli il filtro"
              >
                ✕
              </span>
            </div>
          )}

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
              fMinPrice={fMinPrice}
              onMinPriceChange={p0(setFMinPrice)}
              fMaxPrice={fMaxPrice}
              onMaxPriceChange={p0(setFMaxPrice)}
              fMinDays={fMinDays}
              onMinDaysChange={p0(setFMinDays)}
              fMaxDays={fMaxDays}
              onMaxDaysChange={p0(setFMaxDays)}
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
              depreciation={depreciation}
              trendPaths={trendPaths}
              batchLastRun={batchLastRun}
              category={category}
            />
          )}

          {screen === "tempo" && <TimeToSaleScreen category={category} />}

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

const GRID_COLUMNS = "56px 60px minmax(0, 2.1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.1fr) 84px 104px";

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
  fMinPrice: number | null;
  onMinPriceChange: (v: number | null) => void;
  fMaxPrice: number | null;
  onMaxPriceChange: (v: number | null) => void;
  fMinDays: number | null;
  onMinDaysChange: (v: number | null) => void;
  fMaxDays: number | null;
  onMaxDaysChange: (v: number | null) => void;
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

      {/* Barra filtri: modello/memoria/colore/condizione (iPhone, da facets) +
          prezzo/giorni online (entrambe le categorie). */}
      {(() => {
        const anyFacetFilter =
          props.fModel || props.fStorage !== null || props.fColor || props.fCondition;
        const anyRangeFilter =
          props.fMinPrice !== null || props.fMaxPrice !== null ||
          props.fMinDays !== null || props.fMaxDays !== null;
        return (
          <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
            {props.isTech && (
              <>
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
              </>
            )}
            <NumberRangeField
              label="Prezzo €"
              min={props.fMinPrice}
              max={props.fMaxPrice}
              onMinChange={props.onMinPriceChange}
              onMaxChange={props.onMaxPriceChange}
              step={10}
            />
            <NumberRangeField
              label="Giorni online"
              min={props.fMinDays}
              max={props.fMaxDays}
              onMinChange={props.onMinDaysChange}
              onMaxChange={props.onMaxDaysChange}
            />
            {(anyFacetFilter || anyRangeFilter) && (
              <button
                onClick={() => {
                  props.onModelChange(null);
                  props.onStorageChange(null);
                  props.onColorChange(null);
                  props.onConditionChange(null);
                  props.onMinPriceChange(null);
                  props.onMaxPriceChange(null);
                  props.onMinDaysChange(null);
                  props.onMaxDaysChange(null);
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
        );
      })()}

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

/** Coppia di input numerici min/max per un filtro a range (prezzo, giorni online). */
function NumberRangeField(props: {
  label: string;
  min: number | null;
  max: number | null;
  onMinChange: (v: number | null) => void;
  onMaxChange: (v: number | null) => void;
  step?: number;
}) {
  const active = props.min !== null || props.max !== null;
  const inputStyle: CSSProperties = {
    width: "64px",
    height: "34px",
    background: "transparent",
    border: "none",
    color: "oklch(0.90 0.004 250)",
    fontSize: "13px",
    fontFamily: "inherit",
    outline: "none",
  };
  const parse = (raw: string): number | null => (raw === "" ? null : Number(raw));
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "4px",
        height: "34px",
        background: active ? "var(--accent-soft)" : "oklch(0.20 0.008 250)",
        border: `1px solid ${active ? "var(--accent-border)" : "oklch(0.32 0.01 250)"}`,
        borderRadius: "8px",
        padding: "0 8px",
      }}
    >
      <span style={{ fontSize: "12px", color: active ? "var(--accent-text)" : "oklch(0.62 0.01 250)" }}>
        {props.label}
      </span>
      <input
        type="number"
        placeholder="min"
        value={props.min ?? ""}
        step={props.step ?? 1}
        onChange={(e) => props.onMinChange(parse(e.target.value))}
        style={inputStyle}
      />
      <span style={{ color: "oklch(0.46 0.01 250)" }}>–</span>
      <input
        type="number"
        placeholder="max"
        value={props.max ?? ""}
        step={props.step ?? 1}
        onChange={(e) => props.onMaxChange(parse(e.target.value))}
        style={inputStyle}
      />
    </div>
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
          {/* I badge vanno a capo: su schermi stretti (o con molti badge) prima
              sforavano nella colonna del prezzo. */}
          <div
            style={{
              display: "flex", alignItems: "center", gap: "6px", rowGap: "4px",
              flexWrap: "wrap", marginTop: "3px", minWidth: 0,
            }}
          >
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
            {item.risk && (
              <div
                style={{
                  fontSize: "11px",
                  padding: "1px 7px",
                  borderRadius: "4px",
                  background:
                    item.risk.level === "alto"
                      ? "oklch(0.62 0.22 25 / 0.20)"
                      : item.risk.level === "medio"
                        ? "oklch(0.75 0.16 60 / 0.18)"
                        : "oklch(0.55 0.02 260 / 0.18)",
                  color:
                    item.risk.level === "alto"
                      ? "oklch(0.78 0.19 25)"
                      : item.risk.level === "medio"
                        ? "oklch(0.82 0.15 70)"
                        : "oklch(0.72 0.02 260)",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
                title={item.risk.reasons.join(" · ")}
              >
                {item.risk.label}
              </div>
            )}
            {item.priceWatch && item.priceWatch.motivation === "alto" && (
              <div
                style={{
                  fontSize: "11px",
                  padding: "1px 7px",
                  borderRadius: "4px",
                  background: "oklch(0.72 0.18 150 / 0.16)",
                  color: "oklch(0.82 0.16 150)",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
                title={
                  `Ha già ribassato ${item.priceWatch.dropCount} ${item.priceWatch.dropCount === 1 ? "volta" : "volte"}` +
                  (item.priceWatch.totalDropEur ? ` (−${eur(item.priceWatch.totalDropEur)})` : "") +
                  ": venditore molto motivato"
                }
              >
                ↓ motivato
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
                flex: "1 1 120px",
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
          {item.risk && (
            <div
              style={{
                border: `1px solid ${
                  item.risk.level === "alto"
                    ? "oklch(0.55 0.20 25 / 0.55)"
                    : item.risk.level === "medio"
                      ? "oklch(0.68 0.15 60 / 0.45)"
                      : "oklch(0.40 0.02 260 / 0.5)"
                }`,
                background:
                  item.risk.level === "alto"
                    ? "oklch(0.30 0.10 25 / 0.30)"
                    : item.risk.level === "medio"
                      ? "oklch(0.32 0.08 60 / 0.22)"
                      : "oklch(0.22 0.01 260)",
                borderRadius: "8px",
                padding: "12px 14px",
              }}
            >
              <div
                style={{
                  fontSize: "12.5px",
                  fontWeight: 700,
                  color:
                    item.risk.level === "alto"
                      ? "oklch(0.82 0.18 25)"
                      : item.risk.level === "medio"
                        ? "oklch(0.85 0.14 70)"
                        : "oklch(0.78 0.02 260)",
                  marginBottom: "6px",
                }}
              >
                {item.risk.label} — controlla prima di comprare
              </div>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: "18px",
                  fontSize: "12.5px",
                  lineHeight: 1.6,
                  color: "oklch(0.82 0.008 250)",
                }}
              >
                {item.risk.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
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
    const cc = item.carryCost;
    stats.push({
      label: "Prezzo d'acquisto max",
      value: eur(item.maxBid),
      hint:
        (item.buyAtAsking
          ? "✓ conviene anche al prezzo richiesto"
          : "tetto per centrare il margine obiettivo") +
        (cc ? ` · già al netto di ${eur(cc.totalEur)} di deprezzamento` : ""),
      color: item.buyAtAsking ? "oklch(0.75 0.15 150)" : "oklch(0.80 0.13 75)",
    });
  }
  // Costo di magazzino: quanto vale in meno il pezzo quando riesci a rivenderlo.
  if (item.carryCost) {
    const cc = item.carryCost;
    stats.push({
      label: "Costo di magazzino",
      value: `−${eur(cc.totalEur)}`,
      hint: `si deprezza di ${eur(cc.monthEur)}/mese · ${cc.holdDays}gg ${
        cc.estimatedDays ? "stimati in stock" : "medi di vendita"
      }`,
      color: "oklch(0.72 0.10 40)",
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
  // E — Watch di prezzo: storico completo dei ribassi (quanti, quanto, quando).
  const pw = item.priceWatch;
  if (pw && (pw.totalDropEur || pw.dropCount > 0)) {
    const pieces: string[] = [];
    if (pw.totalDropEur) pieces.push(`−${eur(pw.totalDropEur)}`);
    if (pw.totalDropPct) pieces.push(`−${pw.totalDropPct}%`);
    const motiv =
      pw.motivation === "alto"
        ? "venditore molto motivato: tratta con decisione"
        : "il venditore sta scendendo: c'è margine di trattativa";
    const ago =
      pw.daysSinceLastDrop != null
        ? ` · ultimo ${pw.daysSinceLastDrop === 0 ? "oggi" : `${pw.daysSinceLastDrop}gg fa`}`
        : "";
    stats.push({
      label: `Ribassi (${pw.dropCount})`,
      value: pieces.join(" · ") || "sceso",
      hint: motiv + ago,
      color: pw.motivation === "alto" ? "oklch(0.72 0.18 150)" : "oklch(0.72 0.16 150)",
    });
  } else if (item.priceDrop && item.priceDrop.oldPrice && item.priceDrop.newPrice) {
    stats.push({
      label: "Già ribassato",
      value: `${eur(item.priceDrop.oldPrice)} → ${eur(item.priceDrop.newPrice)}`,
      hint: "il venditore sta scendendo",
      color: "oklch(0.72 0.16 150)",
    });
  }
  if (item.sellerType) {
    const label = sellerTypeLabel(item.sellerType, props.category);
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
      hint: item.repair.items
        .map((r) => {
          const after = r.aftermarket ? `aftermarket ${eur(r.aftermarket.price)} (${r.aftermarket.grade})` : null;
          const apple = r.apple
            ? `Apple ${eur(r.apple.net)}${r.apple.credit ? ` (${eur(r.apple.price)} − ${eur(r.apple.credit)} reso)` : ""}`
            : null;
          const used = r.source === "aftermarket" ? "aftermarket" : "Apple";
          const corr = r.correction
            ? ` (corretto ×${r.correction.ratio} dalle tue ${r.correction.n} riparazioni: ${eur(r.partCost ?? 0)})`
            : "";
          return `${r.label}: ${[after, apple].filter(Boolean).join(" · ")} → nei conti ${used}${corr}${
            r.labor ? ` + ${eur(r.labor)} manodopera` : ""
          }`;
        })
        .join(" | ") +
        (item.repair.resaleAfterRepair
          ? ` | rivendita riparato ≈ ${eur(item.repair.resaleAfterRepair)}` +
            (item.repair.resaleFactor && item.repair.resaleFactor < 1
              ? ` (−${Math.round((1 - item.repair.resaleFactor) * 100)}% ricambi non originali)`
              : "")
          : ""),
      color: "oklch(0.80 0.13 75)",
    });
  }
  if (item.repairTrackRecord) {
    const tr = item.repairTrackRecord;
    stats.push({
      label: `Tue riparazioni · ${tr.guasto}`,
      value: tr.successPct != null ? `${tr.successPct}% riuscite` : "—",
      hint: `${tr.riuscita} riuscite, ${tr.parziale} parziali, ${tr.fallita} fallite su ${tr.n}`,
      color: (tr.successPct ?? 0) >= 80 ? "oklch(0.75 0.15 150)" : "oklch(0.78 0.14 80)",
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

/* --------------------------------------------------- TEMPO DI VENDITA */

type TtsDim = "model" | "color" | "storage";

const TTS_DIM_LABEL: Record<TtsDim, string> = {
  model: "Modello",
  color: "Colore",
  storage: "Taglia",
};

function ttsStorageLabel(st: number | null): string {
  if (st == null) return "n/d";
  return st >= 1024 ? "1TB" : `${st}GB`;
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/* ------------------------- Grafico: prezzo × tempo di vendita × condizione */

// Ordine ORDINALE fisso (mai ciclato): dal migliore al peggiore. Palette
// validata con scripts/validate_palette.js sul fondo scuro #111417 —
// banda di luminosità, chroma, separazione daltonismo e contrasto: tutti PASS.
const COND_ORDER = ["come-nuovo", "buono", "difetti", "rotto"] as const;
const COND_COLOR: Record<string, string> = {
  "come-nuovo": "#11ae5b",
  buono: "#3280dd",
  difetti: "#c18500",
  rotto: "#d73337",
};
const COND_LABEL: Record<string, string> = {
  "come-nuovo": "Come nuovo",
  buono: "Buono",
  difetti: "Con difetti",
  rotto: "Rotto",
};

function SaleScatter(props: { records: TimeToSaleRecord[] }) {
  const [hover, setHover] = useState<{ x: number; y: number; r: TimeToSaleRecord } | null>(null);
  const pts = useMemo(
    () => props.records.filter((r) => r.price != null && r.price > 0),
    [props.records],
  );
  if (pts.length < 5) return null;

  const W = 900, H = 380;
  const M = { top: 16, right: 18, bottom: 40, left: 62 };
  const iw = W - M.left - M.right, ih = H - M.top - M.bottom;

  const maxDays = Math.max(...pts.map((p) => p.days), 1);
  // Il tetto Y taglia il 2% più caro: un singolo outlier schiaccerebbe tutto.
  const sortedP = [...pts.map((p) => p.price as number)].sort((a, b) => a - b);
  const maxPrice = sortedP[Math.floor(sortedP.length * 0.98)] || sortedP[sortedP.length - 1];

  const x = (d: number) => M.left + (Math.min(d, maxDays) / maxDays) * iw;
  const y = (p: number) => M.top + ih - (Math.min(p, maxPrice) / maxPrice) * ih;

  const xTicks = Array.from({ length: 6 }, (_, i) => Math.round((maxDays / 5) * i));
  const yTicks = Array.from({ length: 5 }, (_, i) => Math.round((maxPrice / 4) * i));

  // Mediana dei giorni per fascia di prezzo: la lettura operativa ("a questo
  // prezzo si vende in tot giorni"), che il solo insieme di punti non dà.
  const BANDS = 5;
  const bands = Array.from({ length: BANDS }, (_, i) => {
    const lo = (maxPrice / BANDS) * i, hi = (maxPrice / BANDS) * (i + 1);
    const inBand = pts.filter((p) => (p.price as number) >= lo && (p.price as number) < hi);
    return {
      lo,
      hi,
      med: inBand.length ? median(inBand.map((p) => p.days)) : null,
      n: inBand.length,
    };
  });

  const present = COND_ORDER.filter((c) => pts.some((p) => p.conditionTier === c));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
      {/* Legenda: identità mai affidata al solo colore */}
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
        {present.map((c) => (
          <span key={c} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                width: "10px", height: "10px", borderRadius: "50%",
                background: COND_COLOR[c], flexShrink: 0,
              }}
            />
            <span style={{ fontSize: "12.5px", color: "oklch(0.78 0.01 250)" }}>
              {COND_LABEL[c]}
              <span style={{ color: "oklch(0.5 0.01 250)", fontFamily: MONO }}>
                {" "}({pts.filter((p) => p.conditionTier === c).length})
              </span>
            </span>
          </span>
        ))}
      </div>

      <div style={{ position: "relative", overflowX: "auto" }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: "620px", display: "block" }}>
          {/* Griglia recessiva */}
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke="oklch(0.28 0.01 250)" strokeWidth="1" />
              <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="oklch(0.5 0.01 250)">
                €{t}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={H - 14} textAnchor="middle" fontSize="11" fill="oklch(0.5 0.01 250)">
              {t}gg
            </text>
          ))}

          {/* Mediana giorni per fascia di prezzo */}
          {bands.map((b, i) =>
            b.med != null && b.n >= 3 ? (
              <g key={i}>
                <line
                  x1={x(b.med)} x2={x(b.med)} y1={y(b.hi)} y2={y(b.lo)}
                  stroke="oklch(0.86 0.004 250)" strokeWidth="2" strokeDasharray="3 3" opacity="0.75"
                />
                <text
                  x={x(b.med) + 5} y={y(b.hi) + 13} fontSize="10.5"
                  fill="oklch(0.86 0.004 250)" fontFamily={MONO}
                >
                  {b.med.toFixed(0)}gg
                </text>
              </g>
            ) : null,
          )}

          {/* Punti: anello del colore del fondo per separare le sovrapposizioni */}
          {pts.map((p, i) => (
            <circle
              key={i}
              cx={x(p.days)}
              cy={y(p.price as number)}
              r={hover?.r === p ? 6 : 3.4}
              fill={COND_COLOR[p.conditionTier] ?? "#7a7f87"}
              fillOpacity={hover ? (hover.r === p ? 1 : 0.35) : 0.72}
              stroke="#111417"
              strokeWidth="1"
              onMouseEnter={() => setHover({ x: x(p.days), y: y(p.price as number), r: p })}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            />
          ))}

          <text x={M.left + iw / 2} y={H - 1} textAnchor="middle" fontSize="11" fill="oklch(0.55 0.01 250)">
            giorni per sparire dal mercato →
          </text>
        </svg>

        {hover && (
          <div
            style={{
              position: "absolute",
              left: `min(${(hover.x / W) * 100}%, calc(100% - 210px))`,
              top: `calc(${(hover.y / H) * 100}% - 8px)`,
              transform: "translateY(-100%)",
              background: "oklch(0.16 0.008 250)",
              border: "1px solid oklch(0.34 0.01 250)",
              borderRadius: "8px",
              padding: "8px 10px",
              pointerEvents: "none",
              fontSize: "12px",
              lineHeight: 1.5,
              whiteSpace: "nowrap",
              zIndex: 5,
            }}
          >
            <div style={{ fontWeight: 700 }}>{hover.r.model}</div>
            <div style={{ fontFamily: MONO }}>
              {eur(hover.r.price as number)} · {hover.r.days.toFixed(0)} giorni
            </div>
            <div style={{ color: "oklch(0.65 0.01 250)" }}>
              {COND_LABEL[hover.r.conditionTier] ?? hover.r.conditionTier}
              {hover.r.storageGb ? ` · ${hover.r.storageGb}GB` : ""}
              {hover.r.color ? ` · ${hover.r.color}` : ""}
            </div>
          </div>
        )}
      </div>

      <div style={{ fontSize: "11.5px", color: "oklch(0.55 0.01 250)", lineHeight: 1.6 }}>
        Ogni punto è un annuncio sparito da Subito: <b>a sinistra</b> ciò che è
        andato via in fretta, <b>in alto</b> i prezzi più alti. Le linee tratteggiate sono
        i giorni mediani per fascia di prezzo. Passa sopra un punto per il dettaglio.
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ RIPARAZIONI */

const DEFECT_FILTERS: [string, string][] = [
  ["", "Tutti i guasti"],
  ["schermo-rotto", "Schermo"],
  ["batteria-esausta", "Batteria"],
  ["back-rotto", "Scocca posteriore"],
  ["fotocamera-rotta", "Fotocamera"],
  ["face-id-rotto", "Face ID"],
  ["audio-rotto", "Audio / microfono"],
  ["ricarica-rotta", "Porta di ricarica"],
  ["tasti-rotti", "Tasti"],
];

/** Matrice opportunità modello × guasto: dove conviene cacciare. */
function RepairMatrixScreen(props: { onOpenCell: (cell: RepairCell) => void }) {
  const [data, setData] = useState<RepairMatrix | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [defect, setDefect] = useState("");
  const [showFragile, setShowFragile] = useState(false);
  const [sortBy, setSortBy] = useState<"potential" | "marginGood" | "weekly" | "roi">("potential");

  useEffect(() => {
    const ctrl = new AbortController();
    fetchRepairMatrix(ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setErr(e instanceof Error ? e.message : "Errore");
      });
    return () => ctrl.abort();
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    const key = (c: RepairCell): number => {
      if (sortBy === "weekly") return c.weekly;
      if (sortBy === "marginGood") return c.best?.marginAtGoodBuy ?? -1e9;
      if (sortBy === "roi") return c.best?.roiPct ?? -1e9;
      return c.weeklyPotentialEur ?? -1e9;
    };
    return data.cells
      .filter((c) => (!defect || c.defect === defect) && (showFragile || !c.fragile))
      .sort((a, b) => key(b) - key(a));
  }, [data, defect, showFragile, sortBy]);

  if (err) return <div style={{ color: "oklch(0.68 0.17 25)" }}>Matrice non disponibile: {err}</div>;
  if (!data) return <div style={{ color: "oklch(0.6 0.01 250)" }}>Calcolo della matrice…</div>;

  const r = data.nonOriginalRatios;
  const pct = (x?: number) => (x != null ? `${Math.round((1 - x) * 100)}%` : "—");
  const cols = "1.3fr 1.1fr 0.55fr 0.6fr 0.7fr 0.95fr 0.9fr 0.75fr 0.9fr 0.8fr";
  const head: CSSProperties = {
    fontSize: "10.5px", fontWeight: 700, color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.04em",
  };
  const selectStyle: CSSProperties = { padding: "6px 8px", borderRadius: "8px", fontSize: "13px" };
  const money = (v: number | null | undefined, sign = false) =>
    v == null ? "—" : `${sign && v > 0 ? "+" : ""}${eur(v)}`;
  const tone = (v: number | null | undefined) =>
    v == null ? undefined : v > 0 ? "oklch(0.78 0.15 150)" : "oklch(0.68 0.17 25)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px", animation: "fadeIn 0.2s ease" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Riparazioni · dove conviene cacciare</div>
        <div style={{ fontSize: "13px", color: "oklch(0.6 0.01 250)", marginTop: "6px", lineHeight: 1.6, maxWidth: "900px" }}>
          Per ogni modello e guasto, dagli annunci attivi con <b>solo quel guasto</b>: quanto si paga di solito,
          quanto costa ripararlo, a quanto si rivende riparato e quante occasioni escono a settimana. Il potenziale
          conta solo il quarto più economico degli annunci (il <b>prezzo buono</b>): alla mediana il mercato è già
          giusto. Rivendita con ricambio aftermarket misurata sul mercato: schermo non originale −{pct(r.schermo?.ratio)}
          ({r.schermo?.samples ?? 0} annunci), batteria non originale −{pct(r.batteria?.ratio)}
          ({r.batteria?.samples ?? 0} annunci). Clic su una riga → gli annunci veri.
        </div>
      </div>

      <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "center" }}>
        <select value={defect} onChange={(e) => setDefect(e.target.value)} style={selectStyle}>
          {DEFECT_FILTERS.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)} style={selectStyle}>
          <option value="potential">Ordina: potenziale €/settimana</option>
          <option value="marginGood">Ordina: margine al prezzo buono</option>
          <option value="roi">Ordina: ROI</option>
          <option value="weekly">Ordina: annunci a settimana</option>
        </select>
        <label style={{ fontSize: "13px", display: "flex", gap: "6px", alignItems: "center" }}>
          <input type="checkbox" checked={showFragile} onChange={(e) => setShowFragile(e.target.checked)} />
          mostra anche le celle con meno di 5 annunci
        </label>
        <span style={{ fontSize: "12px", color: "oklch(0.55 0.01 250)" }}>{rows.length} righe</span>
      </div>

      <div style={{ border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px", overflowX: "auto" }}>
        <div style={{ minWidth: "1050px" }}>
          <div
            style={{
              display: "grid", gridTemplateColumns: cols, gap: "10px", padding: "10px 16px",
              background: "oklch(0.2 0.008 250)", ...head,
            }}
          >
            <div>Modello</div>
            <div>Guasto</div>
            <div title="Annunci attivi con solo questo guasto">Annunci</div>
            <div title={`Nuovi a settimana (ultimi ${data.windowDays} giorni)`}>/sett.</div>
            <div title="Mediana dei sani tutti originali">Sano</div>
            <div title="Mediana del prezzo chiesto · prezzo buono (25° percentile)">Acquisto</div>
            <div title="Ricambio della colonna più conveniente + manodopera">Ricambio</div>
            <div title="Rivendita del telefono riparato">Rivendita</div>
            <div title="Margine alla mediana · al prezzo buono">Margine</div>
            <div title="Margine al prezzo buono × occasioni buone a settimana">€/sett.</div>
          </div>
          {rows.map((c) => {
            const b = c.best;
            return (
              <div
                key={`${c.model}-${c.defect}`}
                onClick={() => c.modelKey && props.onOpenCell(c)}
                style={{
                  display: "grid", gridTemplateColumns: cols, gap: "10px", padding: "9px 16px",
                  alignItems: "center", fontSize: "13px", cursor: c.modelKey ? "pointer" : "default",
                  borderTop: "1px solid oklch(0.24 0.008 250)", opacity: c.fragile ? 0.6 : 1,
                }}
              >
                <div style={{ fontWeight: 600 }}>{c.model}</div>
                <div>{c.defectLabel}</div>
                <div style={{ fontFamily: MONO }}>{c.listings}{c.fragile ? " ⚠️" : ""}</div>
                <div style={{ fontFamily: MONO }}>{c.weekly}</div>
                <div style={{ fontFamily: MONO }} title={`${c.healthySamples} sani originali`}>{eur(c.healthyMedian)}</div>
                <div style={{ fontFamily: MONO }}>
                  {eur(c.buyMedian)}
                  <span style={{ color: "oklch(0.6 0.01 250)" }}> · {money(c.buyGood)}</span>
                </div>
                <div
                  style={{ fontFamily: MONO }}
                  title={
                    b
                      ? Object.entries(c.scenarios)
                          .map(([k, s]) => `${k === "apple" ? "Apple" : `aftermarket (${s?.grade})`}: ${eur(s?.partCost ?? 0)} → margine ${eur(s?.margin ?? 0)}`)
                          .join("\n")
                      : "Nessun listino per questo ricambio: il costo lo conosci tu"
                  }
                >
                  {b ? `${eur(b.partCost)} ${b.source === "apple" ? "Apple" : "after."}` : "—"}
                </div>
                <div style={{ fontFamily: MONO }}>{b ? eur(b.resale) : "—"}</div>
                <div style={{ fontFamily: MONO }}>
                  <span style={{ color: tone(b?.margin) }}>{money(b?.margin, true)}</span>
                  <span style={{ color: tone(b?.marginAtGoodBuy) }}> · {money(b?.marginAtGoodBuy, true)}</span>
                  {c.discountSameStorageEur != null && c.discountEur - c.discountSameStorageEur >= 10 && (
                    <div
                      style={{ fontSize: "10.5px", color: "oklch(0.78 0.14 80)" }}
                      title={
                        "Sconto rotto/sano a parità di memoria (i rotti hanno spesso meno GB dei sani):\n" +
                        (c.byStorage ?? [])
                          .map((s) => `${s.storage >= 1024 ? "1TB" : `${s.storage}GB`}: rotto ${eur(s.buyMedian)} vs sano ${eur(s.healthyMedian)} (−${eur(s.discountEur)}, ${s.listings} rotti)`)
                          .join("\n")
                      }
                    >
                      ⚖️ −{eur(c.discountEur - c.discountSameStorageEur)} a pari memoria
                    </div>
                  )}
                </div>
                <div style={{ fontFamily: MONO, fontWeight: 700, color: tone(c.weeklyPotentialEur) }}>
                  {c.weeklyPotentialEur != null ? eur(c.weeklyPotentialEur) : `−${eur(c.discountEur)}`}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ fontSize: "11.5px", color: "oklch(0.55 0.01 250)", lineHeight: 1.6 }}>
        Per i guasti senza listino ricambi (Face ID, audio, ricarica, tasti) l&apos;ultima colonna mostra lo sconto
        rispetto al sano. Manodopera e colonna dei ricambi si impostano in Impostazioni → Riparazioni.
        I tempi di vendita del riparato arriveranno con i venduti (inventario notturno).
      </div>
    </div>
  );
}

function TimeToSaleScreen(props: { category: Category }) {
  const [data, setData] = useState<TimeToSaleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dimensioni su cui raggruppare (qualsiasi sottoinsieme: 0, 1, 2 o 3).
  const [groupBy, setGroupBy] = useState<TtsDim[]>(["model"]);
  // Filtri opzionali per restringere prima di raggruppare.
  const [fModel, setFModel] = useState<string>("");
  const [fColor, setFColor] = useState<string>("");
  const [fStorage, setFStorage] = useState<string>("");

  useEffect(() => {
    const c = new AbortController();
    void Promise.resolve().then(() => {
      if (c.signal.aborted) return;
      setLoading(true);
      setError(null);
      // I filtri sono specifici del verticale: azzerali al cambio.
      setFModel("");
      setFColor("");
      setFStorage("");
    });
    fetchTimeToSale(props.category, c.signal)
      .then((d) => {
        if (c.signal.aborted) return;
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        if (c.signal.aborted || e?.name === "AbortError") return;
        setError("Impossibile caricare i tempi di vendita.");
        setLoading(false);
      });
    return () => c.abort();
  }, [props.category]);

  const toggleDim = (d: TtsDim) =>
    setGroupBy((cur) =>
      cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d],
    );

  const orderedGroup = useMemo(
    () => (["model", "color", "storage"] as TtsDim[]).filter((d) => groupBy.includes(d)),
    [groupBy],
  );

  // Stessi filtri della tabella, ma record grezzi: servono al grafico.
  const filteredRecords = useMemo(
    () =>
      (data?.records ?? []).filter(
        (r) =>
          (!fModel || r.model === fModel) &&
          (!fColor || r.color === fColor) &&
          (!fStorage || String(r.storageGb) === fStorage),
      ),
    [data, fModel, fColor, fStorage],
  );

  const rows = useMemo(() => {
    if (!data) return [];
    const recs = data.records.filter(
      (r) =>
        (!fModel || r.model === fModel) &&
        (!fColor || r.color === fColor) &&
        (!fStorage || String(r.storageGb) === fStorage),
    );
    // Raggruppa per la combinazione di dimensioni attive.
    const groups = new Map<
      string,
      { keys: Record<TtsDim, string>; days: number[]; prices: number[] }
    >();
    for (const r of recs) {
      const keys: Record<TtsDim, string> = {
        model: r.model,
        color: r.color ?? "n/d",
        storage: ttsStorageLabel(r.storageGb),
      };
      const k = orderedGroup.length
        ? orderedGroup.map((d) => keys[d]).join(" · ")
        : "__all__";
      let g = groups.get(k);
      if (!g) {
        g = { keys, days: [], prices: [] };
        groups.set(k, g);
      }
      g.days.push(r.days);
      if (r.price != null) g.prices.push(r.price);
    }
    return [...groups.values()]
      .map((g) => ({
        keys: g.keys,
        avgDays: g.days.reduce((a, b) => a + b, 0) / g.days.length,
        n: g.days.length,
        medianPrice: g.prices.length ? median(g.prices) : null,
      }))
      .sort((a, b) => a.avgDays - b.avgDays);
  }, [data, fModel, fColor, fStorage, orderedGroup]);

  const filteredTotal = rows.reduce((a, r) => a + r.n, 0);
  const overallAvg = filteredTotal
    ? rows.reduce((a, r) => a + r.avgDays * r.n, 0) / filteredTotal
    : null;

  const dimCols = orderedGroup.length
    ? orderedGroup.map(() => "1.2fr").join(" ")
    : "1fr";
  const gridCols = `${dimCols} 0.9fr 0.7fr 1fr`;

  const daysColor = (d: number) =>
    d <= 7
      ? "oklch(0.75 0.15 150)"
      : d <= 21
        ? "oklch(0.78 0.14 75)"
        : "oklch(0.72 0.16 30)";

  const selectStyle: CSSProperties = {
    background: "oklch(0.16 0.008 250)",
    border: "1px solid oklch(0.30 0.01 250)",
    borderRadius: "7px",
    color: "oklch(0.90 0.01 250)",
    padding: "6px 10px",
    fontSize: "13px",
  };

  const chip = (active: boolean): CSSProperties => ({
    padding: "6px 12px",
    borderRadius: "8px",
    fontSize: "13px",
    fontWeight: 600,
    cursor: "pointer",
    userSelect: "none",
    border: active ? "1px solid var(--accent)" : "1px solid oklch(0.30 0.01 250)",
    background: active ? "var(--accent-soft)" : "transparent",
    color: active ? "var(--accent-text)" : "oklch(0.62 0.01 250)",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Tempo di vendita</div>
        <div style={{ fontSize: "13px", color: "oklch(0.55 0.01 250)", marginTop: "4px" }}>
          Giorni medi di vendita dai venduti (annuncio sparito da Subito). Incrocia
          modello, colore e taglia come vuoi.
        </div>
      </div>

      {loading && (
        <div style={{ color: "oklch(0.55 0.01 250)", fontSize: "14px" }}>Carico…</div>
      )}
      {error && <div style={{ color: "oklch(0.72 0.16 30)", fontSize: "14px" }}>{error}</div>}

      {!loading && !error && data && data.sampleSold === 0 && (
        <div
          style={{
            background: "oklch(0.19 0.008 250)",
            border: "1px solid oklch(0.27 0.01 250)",
            borderRadius: "12px",
            padding: "24px",
            color: "oklch(0.60 0.01 250)",
            fontSize: "14px",
            lineHeight: 1.6,
          }}
        >
          Nessun venduto ancora tracciato in questo verticale. Il dato matura man mano
          che il Garbage Collector marca gli annunci spariti come <b>venduto_rimosso</b>:
          servono almeno alcune vendite per stimare i giorni.
        </div>
      )}

      {!loading && !error && data && data.sampleSold > 0 && (
        <>
          {/* Controlli */}
          <div
            style={{
              background: "oklch(0.19 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "12px",
              padding: "16px 18px",
              display: "flex",
              flexDirection: "column",
              gap: "14px",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "oklch(0.55 0.01 250)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Raggruppa per
              </span>
              {(["model", "color", "storage"] as TtsDim[]).map((d) => (
                <div key={d} onClick={() => toggleDim(d)} style={chip(groupBy.includes(d))}>
                  {TTS_DIM_LABEL[d]}
                </div>
              ))}
              <span style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)" }}>
                {orderedGroup.length === 0 ? "→ totale complessivo" : ""}
              </span>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 700,
                  color: "oklch(0.55 0.01 250)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Filtra
              </span>
              <select value={fModel} onChange={(e) => setFModel(e.target.value)} style={selectStyle}>
                <option value="">Tutti i modelli</option>
                {data.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <select value={fColor} onChange={(e) => setFColor(e.target.value)} style={selectStyle}>
                <option value="">Tutti i colori</option>
                {data.colors.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <select value={fStorage} onChange={(e) => setFStorage(e.target.value)} style={selectStyle}>
                <option value="">Tutte le taglie</option>
                {data.storages.map((s) => (
                  <option key={s} value={String(s)}>
                    {ttsStorageLabel(s)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Riepilogo */}
          <div style={{ display: "flex", gap: "14px", flexWrap: "wrap" }}>
            <div
              style={{
                background: "oklch(0.19 0.008 250)",
                border: "1px solid oklch(0.27 0.01 250)",
                borderRadius: "12px",
                padding: "14px 18px",
                minWidth: "180px",
              }}
            >
              <div style={{ fontSize: "11px", color: "oklch(0.55 0.01 250)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 700 }}>
                Media (selezione)
              </div>
              <div style={{ fontFamily: MONO, fontSize: "24px", fontWeight: 700, marginTop: "4px" }}>
                {overallAvg != null ? `${overallAvg.toFixed(1)} gg` : "—"}
              </div>
            </div>
            <div
              style={{
                background: "oklch(0.19 0.008 250)",
                border: "1px solid oklch(0.27 0.01 250)",
                borderRadius: "12px",
                padding: "14px 18px",
                minWidth: "180px",
              }}
            >
              <div style={{ fontSize: "11px", color: "oklch(0.55 0.01 250)", textTransform: "uppercase", letterSpacing: "0.04em", fontWeight: 700 }}>
                Venduti nel campione
              </div>
              <div style={{ fontFamily: MONO, fontSize: "24px", fontWeight: 700, marginTop: "4px" }}>
                {filteredTotal}
              </div>
            </div>
          </div>

          {/* Grafico: dove e quanto in fretta si vende davvero */}
          <div
            style={{
              background: "oklch(0.19 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "12px",
              padding: "18px 20px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <div>
              <div style={{ fontSize: "15px", fontWeight: 700 }}>
                Prezzo × tempo di vendita
              </div>
              <div style={{ fontSize: "12.5px", color: "oklch(0.6 0.01 250)", marginTop: "3px" }}>
                Tutti i {filteredRecords.length.toLocaleString("it-IT")} venduti del filtro
                attivo. La condizione è il colore: è ciò che sposta il prezzo più di
                tutto, quindi si legge invece di essere nascosta.
              </div>
            </div>
            <SaleScatter records={filteredRecords} />
          </div>

          {/* Tabella pivot */}
          <div
            style={{
              background: "oklch(0.19 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "12px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: gridCols,
                gap: "10px",
                padding: "10px 16px",
                borderBottom: "1px solid oklch(0.27 0.01 250)",
                fontSize: "10.5px",
                fontWeight: 700,
                color: "oklch(0.55 0.01 250)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              {orderedGroup.length ? (
                orderedGroup.map((d) => <div key={d}>{TTS_DIM_LABEL[d]}</div>)
              ) : (
                <div>Totale</div>
              )}
              <div style={{ textAlign: "right" }}>Giorni medi</div>
              <div style={{ textAlign: "right" }}>Campione</div>
              <div style={{ textAlign: "right" }}>Prezzo mediano</div>
            </div>
            {rows.length === 0 && (
              <div style={{ padding: "16px", color: "oklch(0.55 0.01 250)", fontSize: "13px" }}>
                Nessun venduto per questa selezione.
              </div>
            )}
            {rows.map((r, i) => {
              const thin = r.n < 3;
              return (
                <div
                  key={i}
                  title={thin ? "Pochi venduti: dato poco affidabile" : undefined}
                  style={{
                    display: "grid",
                    gridTemplateColumns: gridCols,
                    gap: "10px",
                    padding: "11px 16px",
                    alignItems: "center",
                    fontSize: "13px",
                    borderTop: i === 0 ? "none" : "1px solid oklch(0.23 0.008 250)",
                    opacity: thin ? 0.5 : 1,
                  }}
                >
                  {orderedGroup.length ? (
                    orderedGroup.map((d) => (
                      <div key={d} style={{ fontWeight: 600 }}>
                        {r.keys[d]}
                      </div>
                    ))
                  ) : (
                    <div style={{ fontWeight: 600 }}>tutti i venduti</div>
                  )}
                  <div style={{ fontFamily: MONO, fontWeight: 700, textAlign: "right", color: daysColor(r.avgDays) }}>
                    {r.avgDays.toFixed(1)} gg
                  </div>
                  <div style={{ fontFamily: MONO, textAlign: "right", color: "oklch(0.60 0.01 250)" }}>
                    {r.n}
                    {thin ? " ⚠" : ""}
                  </div>
                  <div style={{ fontFamily: MONO, textAlign: "right" }}>
                    {r.medianPrice != null ? eur(r.medianPrice) : "—"}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ fontSize: "12px", color: "oklch(0.46 0.01 250)" }}>
            Ordinato dal più veloce da vendere. Le righe con meno di 3 venduti (⚠) sono
            statisticamente fragili. Solo annunci in condizioni sane.
          </div>
        </>
      )}
    </div>
  );
}

function PipelineScreen(props: {
  deals: Deal[];
  summary: DealsSummary | null;
  onUpdate: (
    id: string,
    patch: Partial<Pick<Deal, "stage" | "buy_price" | "sell_price" | "repair">>,
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

      {summary != null && summary.staleDeals > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            background: "oklch(0.22 0.05 60)",
            border: "1px solid oklch(0.38 0.09 60)",
            borderRadius: "12px",
            padding: "14px 18px",
            fontSize: "13px",
          }}
        >
          <span style={{ fontSize: "18px" }}>⏳</span>
          <div>
            <b>
              {summary.staleDeals} {summary.staleDeals === 1 ? "affare fermo" : "affari fermi"}
              {summary.staleCriticalDeals > 0 && ` (${summary.staleCriticalDeals} critici)`}
            </b>
            <div style={{ color: "oklch(0.72 0.02 60)", marginTop: "2px" }}>
              {summary.staleCarryLossEur != null
                ? `Il deprezzamento maturato mentre restano invenduti vale già ${eur(summary.staleCarryLossEur)}: sbloccali o abbassa il prezzo.`
                : "Sbloccali: o si muovono, o smettono di essere affari."}
            </div>
          </div>
        </div>
      )}

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

      {summary && (summary.repairs ?? 0) > 0 && (
        <div
          style={{
            background: "oklch(0.185 0.008 250)", border: "1px solid oklch(0.27 0.01 250)",
            borderRadius: "12px", padding: "16px 20px", display: "flex", gap: "28px",
            flexWrap: "wrap", alignItems: "center", fontSize: "13px",
          }}
        >
          <div style={{ fontSize: "14px", fontWeight: 700 }}>🔧 Le tue riparazioni</div>
          <div>
            <div style={cardLabel}>Riuscite</div>
            <div style={{ fontFamily: MONO, fontSize: "18px", fontWeight: 700, marginTop: "4px" }}>
              {summary.repairSuccessPct != null ? `${summary.repairSuccessPct}%` : "—"}
              <span style={{ fontSize: "11px", color: "oklch(0.55 0.01 250)", marginLeft: "6px" }}>
                su {summary.repairs} ({summary.repairOutcomes?.parziale ?? 0} parziali,{" "}
                {summary.repairOutcomes?.fallita ?? 0} fallite)
              </span>
            </div>
          </div>
          <div>
            <div style={cardLabel}>Ricambi: reale − stima</div>
            <div style={{ fontFamily: MONO, fontSize: "18px", fontWeight: 700, marginTop: "4px" }}>
              {summary.repairCostBiasEur != null
                ? `${summary.repairCostBiasEur >= 0 ? "+" : ""}${eur(summary.repairCostBiasEur)}`
                : "—"}
            </div>
          </div>
          <div>
            <div style={cardLabel}>Tempo medio</div>
            <div style={{ fontFamily: MONO, fontSize: "18px", fontWeight: 700, marginTop: "4px" }}>
              {summary.avgRepairMinutes != null ? `${summary.avgRepairMinutes} min` : "—"}
            </div>
          </div>
          {summary.repairFeedback && <RepairFeedbackLine fb={summary.repairFeedback} />}
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
    patch: Partial<Pick<Deal, "stage" | "buy_price" | "sell_price" | "repair">>,
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
  const [repairOpen, setRepairOpen] = useState(false);

  return (
    <div style={{ borderTop: "1px solid oklch(0.24 0.008 250)" }}>
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "2.2fr 1.3fr 1fr 1fr 1fr 40px",
        gap: "12px",
        padding: "12px 16px",
        alignItems: "center",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: "13px", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {deal.title ?? "—"}
        </div>
        {deal.stale && (
          <div
            title={`Fermo in questo stadio da ${deal.stale.days} giorni (soglia ${deal.stale.limit})`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              marginTop: "3px",
              padding: "2px 7px",
              borderRadius: "5px",
              fontSize: "10.5px",
              fontWeight: 700,
              background:
                deal.stale.level === "critico"
                  ? "oklch(0.30 0.10 25)"
                  : "oklch(0.30 0.07 75)",
              color:
                deal.stale.level === "critico"
                  ? "oklch(0.82 0.15 25)"
                  : "oklch(0.85 0.13 75)",
            }}
          >
            {deal.stale.level === "critico" ? "🛑" : "⏳"} fermo da {deal.stale.days}gg
            {deal.stale.carryLossEur != null && (
              <span style={{ fontFamily: MONO, opacity: 0.9 }}>
                · −{eur(deal.stale.carryLossEur)}
              </span>
            )}
          </div>
        )}
        <div style={{ fontSize: "11px", color: "oklch(0.46 0.01 250)", fontFamily: MONO }}>
          {deal.category === "automobile" ? "🚗" : "📱"}{" "}
          {deal.estimatedMarginEur != null ? `stima +${eur(deal.estimatedMarginEur)}` : ""}
          {" · "}
          <span
            onClick={() => setRepairOpen((v) => !v)}
            style={{ color: "var(--accent-text)", cursor: "pointer" }}
            title="Pezzi montati, costo reale, tempo ed esito"
          >
            🔧 {deal.repairOutcome
              ? `${deal.repairOutcome}${deal.repairCost != null ? ` · ricambi ${eur(deal.repairCost)}` : ""}`
              : "riparazione"} {repairOpen ? "▾" : "▸"}
          </span>
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
    {repairOpen && (
      <RepairEditor deal={deal} onSave={(repair) => props.onUpdate(deal.id, { repair })} />
    )}
    </div>
  );
}

const REPAIR_PARTS = ["schermo", "batteria", "scocca", "fotocamera", "face-id", "audio", "ricarica", "tasti", "altro"];

/** Riparazione vera di un affare: pezzi (fonte + costo), minuti, esito. */
function RepairEditor(props: { deal: Deal; onSave: (repair: DealRepair) => Promise<void> }) {
  const { deal } = props;
  const [parts, setParts] = useState<DealRepair["parts"]>(deal.repair?.parts ?? []);
  const [minutes, setMinutes] = useState<string>(deal.repair?.minutes != null ? String(deal.repair.minutes) : "");
  const [outcome, setOutcome] = useState<string>(deal.repair?.outcome ?? "");
  const [saved, setSaved] = useState(false);
  const est = deal.estimate;
  const inp: CSSProperties = {
    height: "30px", background: "oklch(0.16 0.008 250)", border: "1px solid oklch(0.30 0.01 250)",
    borderRadius: "6px", color: "oklch(0.94 0.004 250)", padding: "0 8px", fontSize: "12.5px",
  };
  const setPart = (i: number, patch: Partial<DealRepair["parts"][number]>) =>
    setParts((cur) => cur.map((p, k) => (k === i ? { ...p, ...patch } : p)));

  return (
    <div style={{ padding: "4px 16px 16px 16px", display: "flex", flexDirection: "column", gap: "10px", fontSize: "12.5px" }}>
      {est && (
        <div style={{ color: "oklch(0.62 0.01 250)" }}>
          Stima all&apos;aggancio:{" "}
          {est.repairItems?.length
            ? est.repairItems.map((r) => `${r.part} ${eur(r.cost)} (${r.source ?? "?"})`).join(", ")
            : "nessuna riparazione prevista"}
          {est.resaleAfterRepair ? ` · rivendita riparato ≈ ${eur(est.resaleAfterRepair)}` : ""}
          {est.marginEur != null ? ` · margine ${eur(est.marginEur)}` : ""}
        </div>
      )}
      {parts.map((p, i) => (
        <div key={i} style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <select value={p.part} onChange={(e) => setPart(i, { part: e.target.value })} style={inp}>
            {REPAIR_PARTS.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <select
            value={p.source}
            onChange={(e) => setPart(i, { source: e.target.value as DealRepair["parts"][number]["source"] })}
            style={inp}
          >
            <option value="aftermarket">aftermarket</option>
            <option value="apple">originale Apple</option>
            <option value="usato">usato / da donatore</option>
          </select>
          <input
            value={p.cost || ""}
            placeholder="€ costo"
            inputMode="decimal"
            onChange={(e) => setPart(i, { cost: Number(e.target.value.replace(",", ".")) || 0 })}
            style={{ ...inp, width: "90px", fontFamily: MONO }}
          />
          <span onClick={() => setParts((cur) => cur.filter((_, k) => k !== i))} style={{ cursor: "pointer" }} title="Togli">
            ✕
          </span>
        </div>
      ))}
      <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
        <span
          onClick={() => setParts((cur) => [...cur, { part: "schermo", source: "aftermarket", cost: 0 }])}
          style={{ color: "var(--accent-text)", cursor: "pointer" }}
        >
          + pezzo
        </span>
        <input
          value={minutes}
          placeholder="minuti di lavoro"
          inputMode="numeric"
          onChange={(e) => setMinutes(e.target.value.replace(/\D/g, ""))}
          style={{ ...inp, width: "130px" }}
        />
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)} style={inp}>
          <option value="">esito…</option>
          <option value="riuscita">riuscita</option>
          <option value="parziale">parziale</option>
          <option value="fallita">fallita</option>
        </select>
        <button
          onClick={async () => {
            await props.onSave({
              parts: parts.filter((p) => p.cost > 0),
              minutes: minutes ? Number(minutes) : null,
              outcome: (outcome || null) as DealRepair["outcome"],
            });
            setSaved(true);
            setTimeout(() => setSaved(false), 1500);
          }}
          style={{ ...inp, cursor: "pointer", background: "var(--accent)", color: "oklch(0.12 0.008 250)", fontWeight: 700 }}
        >
          {saved ? "Salvato ✓" : "Salva riparazione"}
        </button>
        <span style={{ color: "oklch(0.55 0.01 250)" }}>
          I ricambi vanno qui (non nei costi extra): entrano nell&apos;investito e nel confronto con la stima.
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ INTEL */

function IntelScreen(props: {
  loading: boolean;
  error: string | null;
  intel: ApiTrends | null;
  depreciation: DepreciationData | null;
  trendPaths: { linePath: string; areaPath: string; min: number; max: number } | null;
  batchLastRun: string;
  category: Category;
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

          <DepreciationSection data={props.depreciation} />

          <SellerRanking sellers={intel?.sellers ?? []} category={props.category} />
        </>
      )}
    </div>
  );
}

// Colore per linea di prodotto: la stessa linea tiene il colore fra grafico,
// legenda e tabella, così l'occhio segue una generazione sola.
const LINE_COLORS: Record<string, string> = {
  "": "oklch(0.70 0.15 250)",
  mini: "oklch(0.75 0.13 200)",
  plus: "oklch(0.72 0.15 300)",
  pro: "oklch(0.75 0.15 150)",
  "pro-max": "oklch(0.78 0.15 75)",
  e: "oklch(0.72 0.15 20)",
};

function lineColor(line: string): string {
  return LINE_COLORS[line] ?? "oklch(0.70 0.02 250)";
}

function DepreciationSection(props: { data: DepreciationData | null }) {
  const { data } = props;
  const [storage, setStorage] = useState<number | null>(128);

  const curves = useMemo(
    () => (data?.curves ?? []).filter((c) => c.storage === storage),
    [data, storage],
  );

  if (!data || !data.supported || data.curves.length === 0) return null;

  const summary = data.summary;
  const rows = [...curves]
    .flatMap((c) => c.points)
    .sort((a, b) => (b.loss12mPct ?? -1) - (a.loss12mPct ?? -1));

  const card: CSSProperties = {
    background: "oklch(0.19 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "22px",
  };
  const header: CSSProperties = {
    fontSize: "11px",
    fontWeight: 600,
    color: "oklch(0.46 0.01 250)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    textAlign: "right",
    padding: "0 10px 8px",
  };
  const cell: CSSProperties = {
    fontFamily: MONO,
    fontSize: "13px",
    textAlign: "right",
    padding: "9px 10px",
    borderTop: "1px solid oklch(0.24 0.01 250)",
  };
  const chip = (active: boolean): CSSProperties => ({
    padding: "5px 12px",
    borderRadius: "999px",
    fontSize: "12px",
    fontWeight: 600,
    cursor: "pointer",
    border: `1px solid ${active ? "var(--accent)" : "oklch(0.30 0.01 250)"}`,
    background: active ? "oklch(0.28 0.06 250)" : "transparent",
    color: active ? "var(--accent)" : "oklch(0.62 0.01 250)",
  });

  return (
    <div style={card}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "16px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: "14px", fontWeight: 700 }}>
            📉 Curva di deprezzamento
          </div>
          <div
            style={{
              fontSize: "12.5px",
              color: "oklch(0.62 0.01 250)",
              marginTop: "3px",
              maxWidth: "620px",
            }}
          >
            Prezzo mediano per età del modello, a parità di linea e memoria. Il 14
            Pro di oggi è quanto varrà il 15 Pro fra un anno: da lì la perdita
            attesa e il costo di tenerlo fermo in magazzino.
          </div>
        </div>
        <div style={{ display: "flex", gap: "6px" }}>
          <div onClick={() => setStorage(null)} style={chip(storage === null)}>
            tutte
          </div>
          {data.storages.map((s) => (
            <div key={s} onClick={() => setStorage(s)} style={chip(storage === s)}>
              {s >= 1024 ? "1TB" : `${s}GB`}
            </div>
          ))}
        </div>
      </div>

      {(summary.best || summary.worst) && (
        <div
          style={{
            display: "flex",
            gap: "22px",
            flexWrap: "wrap",
            margin: "16px 0 4px",
            fontSize: "12.5px",
          }}
        >
          {summary.best && (
            <div>
              <span style={{ color: "oklch(0.46 0.01 250)" }}>Tiene il valore </span>
              <b style={{ color: "oklch(0.75 0.15 150)" }}>
                {summary.best.model} {summary.best.storageLabel}
              </b>{" "}
              <span style={{ fontFamily: MONO }}>−{summary.best.loss12mPct}%/anno</span>
            </div>
          )}
          {summary.worst && (
            <div>
              <span style={{ color: "oklch(0.46 0.01 250)" }}>Brucia di più </span>
              <b style={{ color: "oklch(0.72 0.16 25)" }}>
                {summary.worst.model} {summary.worst.storageLabel}
              </b>{" "}
              <span style={{ fontFamily: MONO }}>−{summary.worst.loss12mPct}%/anno</span>
            </div>
          )}
          {summary.avgLoss12mPct != null && (
            <div>
              <span style={{ color: "oklch(0.46 0.01 250)" }}>Media gamma </span>
              <span style={{ fontFamily: MONO }}>−{summary.avgLoss12mPct}%/anno</span>
            </div>
          )}
        </div>
      )}

      {curves.length > 0 ? (
        <>
          <DepreciationChart curves={curves} />
          <div style={{ display: "flex", gap: "14px", flexWrap: "wrap", marginTop: "10px" }}>
            {curves.map((c) => (
              <div
                key={c.line}
                style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px" }}
              >
                <span
                  style={{
                    width: "14px",
                    height: "3px",
                    borderRadius: "2px",
                    background: lineColor(c.line),
                  }}
                />
                <span style={{ color: "oklch(0.72 0.01 250)" }}>{c.lineLabel}</span>
                <span style={{ color: "oklch(0.46 0.01 250)", fontFamily: MONO }}>
                  n={c.sample}
                </span>
              </div>
            ))}
          </div>

          <div style={{ overflowX: "auto", marginTop: "18px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "720px" }}>
              <thead>
                <tr>
                  <th style={{ ...header, textAlign: "left" }}>Modello</th>
                  <th style={header}>Età</th>
                  <th style={header}>Mediana</th>
                  <th style={header}>Valore residuo</th>
                  <th style={header}>Perdita 12 mesi</th>
                  <th style={header}>Costo magazzino</th>
                  <th style={header}>Campione</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={`${p.modelKey}-${p.storageLabel}`}>
                    <td style={{ ...cell, textAlign: "left", fontFamily: "inherit" }}>
                      <span
                        style={{
                          display: "inline-block",
                          width: "8px",
                          height: "8px",
                          borderRadius: "50%",
                          background: lineColor(p.line),
                          marginRight: "8px",
                        }}
                      />
                      {p.model}
                      <span style={{ color: "oklch(0.46 0.01 250)" }}> {p.storageLabel}</span>
                    </td>
                    <td style={{ ...cell, color: "oklch(0.62 0.01 250)" }}>
                      {p.ageYears.toFixed(1)}a
                    </td>
                    <td style={{ ...cell, fontWeight: 700 }}>{eur(p.median)}</td>
                    <td style={cell}>
                      {p.retentionPct != null ? (
                        <span style={{ color: retentionColor(p.retentionPct) }}>
                          {p.retentionPct}%
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={cell}>
                      {p.loss12mPct != null ? (
                        <span
                          title={`Stimato dal salto verso ${p.vsModel}`}
                          style={{ color: lossColor(p.loss12mPct) }}
                        >
                          −{eur(p.loss12mEur ?? 0)} · {p.loss12mPct}%
                        </span>
                      ) : (
                        <span style={{ color: "oklch(0.40 0.01 250)" }}>
                          generazione più vecchia
                        </span>
                      )}
                    </td>
                    <td style={cell}>
                      {p.carryCostMonthEur != null ? (
                        <span style={{ color: "oklch(0.62 0.01 250)" }}>
                          {eur(p.carryCostMonthEur)}/mese
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ ...cell, color: "oklch(0.46 0.01 250)" }}>{p.sample}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: "11.5px", color: "oklch(0.46 0.01 250)", marginTop: "10px" }}>
            Valore residuo = rispetto al modello più recente della stessa linea. Le
            mediane vengono dagli annunci attivi sani (outlier esclusi con IQR);
            servono almeno 3 annunci per variante e 2 generazioni per tracciare una
            curva.
          </div>
        </>
      ) : (
        <div
          style={{
            padding: "28px",
            textAlign: "center",
            color: "oklch(0.46 0.01 250)",
            fontSize: "13px",
          }}
        >
          Campione insufficiente per questo taglio di memoria.
        </div>
      )}
    </div>
  );
}

function retentionColor(pct: number): string {
  if (pct >= 80) return "oklch(0.75 0.15 150)";
  if (pct >= 60) return "oklch(0.80 0.14 85)";
  return "oklch(0.72 0.16 25)";
}

function lossColor(pct: number): string {
  if (pct <= 12) return "oklch(0.75 0.15 150)";
  if (pct <= 22) return "oklch(0.80 0.14 85)";
  return "oklch(0.72 0.16 25)";
}

function DepreciationChart(props: { curves: DepreciationCurve[] }) {
  const { curves } = props;
  const W = 600;
  const H = 230;
  const padL = 46;
  const padR = 14;
  const padT = 14;
  const padB = 30;

  const points: DepreciationPoint[] = curves.flatMap((c) => c.points);
  if (points.length === 0) return null;

  const ages = points.map((p) => p.ageYears);
  const minAge = Math.min(...ages);
  const maxAge = Math.max(...ages);
  const maxPrice = Math.max(...points.map((p) => p.median));
  const ageSpan = maxAge - minAge || 1;

  const x = (age: number) => padL + ((age - minAge) / ageSpan) * (W - padL - padR);
  // Asse Y sempre ancorato a 0: la caduta si legge in proporzione al valore.
  const y = (price: number) => padT + (1 - price / (maxPrice * 1.1)) * (H - padT - padB);

  const gridPrices = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(maxPrice * 1.1 * f));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", height: "260px", display: "block", marginTop: "14px" }}
    >
      {gridPrices.map((price) => (
        <g key={price}>
          <line
            x1={padL}
            x2={W - padR}
            y1={y(price)}
            y2={y(price)}
            stroke="oklch(0.26 0.01 250)"
            strokeWidth="1"
          />
          <text
            x={padL - 8}
            y={y(price) + 4}
            textAnchor="end"
            fontSize="10"
            fill="oklch(0.46 0.01 250)"
          >
            {price}€
          </text>
        </g>
      ))}

      {curves.map((c) => {
        const sorted = [...c.points].sort((a, b) => a.ageYears - b.ageYears);
        const path = sorted
          .map((p, i) => `${i === 0 ? "M" : "L"} ${x(p.ageYears)} ${y(p.median)}`)
          .join(" ");
        return (
          <g key={c.line}>
            <path
              d={path}
              fill="none"
              stroke={lineColor(c.line)}
              strokeWidth="2.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {sorted.map((p) => (
              <circle
                key={p.modelKey}
                cx={x(p.ageYears)}
                cy={y(p.median)}
                r="4"
                fill="oklch(0.19 0.008 250)"
                stroke={lineColor(c.line)}
                strokeWidth="2"
              >
                <title>
                  {`${p.model} ${p.storageLabel} · ${p.ageYears.toFixed(1)} anni · ${p.median}€ (n=${p.sample})`}
                </title>
              </circle>
            ))}
          </g>
        );
      })}

      {/* Asse X: l'età in anni, un tick per generazione presente. */}
      {[...new Set(points.map((p) => Math.round(p.ageYears * 10) / 10))].map((age) => (
        <text
          key={age}
          x={x(age)}
          y={H - 10}
          textAnchor="middle"
          fontSize="10"
          fill="oklch(0.46 0.01 250)"
        >
          {age.toFixed(1)}a
        </text>
      ))}
    </svg>
  );
}

function SellerRanking(props: { sellers: SellerRankRow[]; category: Category }) {
  const { sellers } = props;
  if (sellers.length === 0) return null;
  const typeLabel = (t: string | null) => sellerTypeLabel(t, props.category);
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
        <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
          {m.name}
          {m.liquidityLevel && (
            <span
              title={`Liquidità ${m.liquidityLevel}${m.liquidityScore != null ? ` (${m.liquidityScore}/100)` : ""}: quanto in fretta gira il capitale (sell-through, giorni di vendita, domanda)`}
              style={{
                fontSize: "9.5px",
                fontWeight: 700,
                padding: "1px 5px",
                borderRadius: "4px",
                textTransform: "uppercase",
                letterSpacing: "0.03em",
                whiteSpace: "nowrap",
                background:
                  m.liquidityLevel === "alta"
                    ? "oklch(0.72 0.16 150 / 0.16)"
                    : m.liquidityLevel === "media"
                      ? "oklch(0.75 0.14 75 / 0.16)"
                      : "oklch(0.70 0.16 30 / 0.16)",
                color:
                  m.liquidityLevel === "alta"
                    ? "oklch(0.80 0.15 150)"
                    : m.liquidityLevel === "media"
                      ? "oklch(0.82 0.14 75)"
                      : "oklch(0.78 0.16 30)",
              }}
            >
              💧 {m.liquidityLevel}
            </span>
          )}
        </div>
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
        <div
          style={{ fontFamily: MONO }}
          title={
            m.avgDaysToSell == null
              ? undefined
              : m.daysToSellKM != null
                ? `Kaplan–Meier: conta anche chi è ancora online. Media dei soli venduti: ${m.avgDaysToSell}gg (ottimista)`
                : `Meno di metà degli annunci si è venduta nel periodo osservato: il tempo tipico non è ancora misurabile. Media dei soli venduti: ${m.avgDaysToSell}gg (ottimista)`
          }
        >
          {m.daysToSellKM != null ? `${m.daysToSellKM}gg` : m.avgDaysToSell != null ? "n/d" : "—"}
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

      {/* F — Liquidità per variante */}
      {m.liquidityLevel && (
        <div style={block}>
          <div style={blkLabel}>💧 Liquidità (quanto gira)</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            <div
              style={{
                color:
                  m.liquidityLevel === "alta"
                    ? "oklch(0.75 0.15 150)"
                    : m.liquidityLevel === "media"
                      ? "oklch(0.78 0.14 75)"
                      : "oklch(0.72 0.16 30)",
              }}
              title="Sintesi di sell-through, giorni di vendita e domanda/offerta: quanto in fretta rientra il capitale"
            >
              {m.liquidityLevel}
              {m.liquidityScore != null ? ` · ${m.liquidityScore}/100` : ""}{" "}
              {m.liquidityLevel === "alta"
                ? "↑ gira in fretta"
                : m.liquidityLevel === "media"
                  ? "→ nella media"
                  : "↓ capitale fermo"}
            </div>
            {m.sellThroughRate != null && <div>sell-through {m.sellThroughRate}%</div>}
            {m.daysToSellKM != null ? (
              <div>metà si vende entro ~{m.daysToSellKM}gg</div>
            ) : (
              m.avgDaysToSell != null && <div>i venduti spariscono in ~{m.avgDaysToSell}gg</div>
            )}
            {m.sold7dPct != null && (
              <div>
                venduto entro 7gg: {m.sold7dPct}% · entro 30gg: {m.sold30dPct}%
              </div>
            )}
            {m.removalKinds && Object.keys(m.removalKinds).length > 0 && (
              <div title="Stima: oltre 11 mesi = scaduto; ≥90gg, mai ribassato e sopra mercato = ritirato">
                spariti: {Object.entries(m.removalKinds)
                  .map(([k, n]) => `${n} ${k}`)
                  .join(" · ")}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Premio memoria + offerta per taglio (F — liquidità/volume per variante) */}
      {storages.length > 0 && (
        <div style={block}>
          <div style={blkLabel}>Memoria: mediana · annunci attivi</div>
          <div style={{ fontFamily: MONO, fontSize: "12px", lineHeight: 1.7 }}>
            {storages.map(([st, price]) => {
              const vol = m.storageVolume[st];
              return (
                <div key={st}>
                  {Number(st) >= 1024 ? "1TB" : `${st}GB`}: {eur(price)}
                  {vol ? (
                    <span style={{ color: "oklch(0.55 0.01 250)" }}> · {vol} attivi</span>
                  ) : null}
                </div>
              );
            })}
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
  inventory_tech: "📦",
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
  // key: il campo viene usato anche dentro .map() (margini per categoria, chat
  // Telegram) e il titolo è univoco in ciascuna lista.
  const field = (title: string, node: ReactNode) => (
    <div key={title}>
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
          {field(
            "Riparazioni: margine netto minimo",
            num(s.alert_min_repair_margin_eur ?? 60, (v) => setS({ ...s, alert_min_repair_margin_eur: v }), "€"),
          )}
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

      {/* Riparazioni: colonna di costo, credito Apple, manodopera */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Riparazioni</div>
        <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "-6px", lineHeight: 1.6 }}>
          Prezzi dei ricambi per modello da due listini: originali Apple (Self Service Repair,
          IVA inclusa) e aftermarket (Soft OLED / Incell, batterie Deji). Si aggiornano con{" "}
          <code>scripts/fetch_apple_parts.py</code> e <code>scripts/fetch_aftermarket_parts.py</code>.
        </div>
        <div style={{ display: "flex", gap: "24px", flexWrap: "wrap", alignItems: "flex-end" }}>
          {field(
            "Ricambi usati nei conti",
            <select
              value={s.repair_source ?? "aftermarket"}
              onChange={(e) => setS({ ...s, repair_source: e.target.value as "aftermarket" | "apple" })}
              style={{ padding: "6px 8px", borderRadius: "8px" }}
            >
              <option value="aftermarket">Aftermarket</option>
              <option value="apple">Originali Apple</option>
            </select>,
          )}
          {field(
            "Credito reso Apple",
            <label style={{ display: "flex", gap: "6px", alignItems: "center", fontSize: "13px" }}>
              <input
                type="checkbox"
                checked={s.apple_return_credit ?? true}
                onChange={(e) => setS({ ...s, apple_return_credit: e.target.checked })}
              />
              rispedisco la parte vecchia
            </label>,
          )}
          {Object.entries(s.repair_labor_eur ?? {}).map(([part, v]) =>
            field(
              `Manodopera ${part}`,
              num(v, (nv) => setS({ ...s, repair_labor_eur: { ...s.repair_labor_eur, [part]: nv } }), "€"),
            ),
          )}
        </div>
      </div>

      {/* Ricambi Apple per fascia: ripiego per i modelli senza listino */}
      <div style={card}>
        <div style={{ fontSize: "15px", fontWeight: 700 }}>Ripiego: prezzi Apple per fascia</div>
        <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "-6px" }}>
          Usati solo per i modelli che non compaiono in nessuno dei due listini.
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
                  {last.requests != null ? ` · ${last.requests} richieste` : ""}
                  {last.gaps ? ` · ⚠ ${last.gaps} target con annunci persi (cadenza troppo lenta)` : ""}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: "12px", color: "oklch(0.55 0.01 250)" }}>
        {health.pacing && (
          <>
            Ritmo: 1 richiesta ogni ~{health.pacing.gapS}s (minimo {health.pacing.minGapS}s)
            {health.pacing.blockedForS > 0
              ? ` · ⏸ in pausa anti-blocco ancora ${Math.ceil(health.pacing.blockedForS / 60)} min`
              : ""}
            {health.pacing.totalBlocks > 0 ? ` · blocchi dall'avvio: ${health.pacing.totalBlocks}` : ""} ·{" "}
          </>
        )}
        {health.proxy_configured ? "proxy configurato · " : "connessione diretta · "}
        impronte TLS: {health.impersonate_pool?.join(", ") || "—"}
      </div>
      {cats.map(([cat, label]) => {
        const rows = health.coverage[cat]?.targets ?? [];
        return rows.length ? <TargetCoverageTable key={cat} label={label} rows={rows} /> : null;
      })}
      <DataQualityPanel />
    </div>
  );
}

const QUALITY_FIELD_LABELS: Record<string, string> = {
  modelloRiconosciuto: "Modello riconosciuto",
  memoria: "Memoria",
  colore: "Colore",
  batteria: "Batteria",
  dataPubblicazione: "Data di pubblicazione",
  foto: "Foto",
  target: "Target assegnato",
  venditore: "Venditore",
};

/** Quanto fidarsi delle metriche: copertura vs Subito, campi estratti, raccolta. */
function DataQualityPanel() {
  const [q, setQ] = useState<DataQuality | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    const load = () => fetchDataQuality("smartphone", ctrl.signal).then(setQ).catch(() => null);
    Promise.resolve().then(load);
    const poll = setInterval(load, 60000);
    return () => {
      ctrl.abort();
      clearInterval(poll);
    };
  }, []);
  if (!q) return null;
  const cov = q.coverage;
  const head: CSSProperties = {
    fontSize: "10.5px", fontWeight: 700, color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.04em",
  };
  const tone = (pct: number) =>
    pct >= 80 ? "var(--accent)" : pct >= 50 ? "oklch(0.78 0.14 80)" : "oklch(0.68 0.17 25)";
  return (
    <div
      style={{
        border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px",
        padding: "14px 16px", display: "flex", flexDirection: "column", gap: "12px",
      }}
    >
      <div>
        <div style={{ fontSize: "14px", fontWeight: 700 }}>Qualità del dato · iPhone</div>
        <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "2px", lineHeight: 1.6 }}>
          {q.activeListings.toLocaleString("it-IT")} annunci attivi in archivio
          {cov.subitoTotal != null && cov.seenLastInventory != null ? (
            <>
              {" "}· ultimo inventario: letti <b>{(cov.readLastInventory ?? cov.seenLastInventory).toLocaleString("it-IT")}</b> su{" "}
              {cov.subitoTotal.toLocaleString("it-IT")} dichiarati da Subito ({cov.seenPct}%),{" "}
              {cov.seenLastInventory.toLocaleString("it-IT")} iPhone
              {cov.inventoryComplete === false ? " · inventario incompleto" : ""}
              {cov.inventoryAt ? ` · ${relativeTime(cov.inventoryAt)}` : ""}
            </>
          ) : (
            " · copertura vs Subito disponibile dopo il primo inventario notturno"
          )}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "10px" }}>
        {Object.entries(q.fieldsPct).map(([k, pct]) => (
          <div key={k} style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
              <span>{QUALITY_FIELD_LABELS[k] ?? k}</span>
              <span style={{ fontFamily: MONO, fontWeight: 700 }}>{pct}%</span>
            </div>
            <div style={{ height: "5px", borderRadius: "3px", background: "oklch(0.24 0.008 250)", overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: tone(pct) }} />
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: "18px", flexWrap: "wrap", fontSize: "12px" }}>
        <span style={head}>Ultime 24h</span>
        <span>{q.last24h.runs} giri</span>
        <span>{q.last24h.requests.toLocaleString("it-IT")} richieste</span>
        <span>+{q.last24h.new.toLocaleString("it-IT")} nuovi</span>
        <span style={{ color: q.last24h.gaps ? "oklch(0.68 0.17 25)" : undefined }}>
          {q.last24h.gaps} giri con annunci persi
        </span>
        <span style={{ color: q.last24h.down ? "oklch(0.68 0.17 25)" : undefined }}>
          {q.last24h.down} giri down
        </span>
        <span>{q.removed7d.toLocaleString("it-IT")} spariti in 7 giorni</span>
        {q.inventoryResult && (
          <span
            style={{
              color: q.inventoryResult.aborted || q.inventoryResult.complete === false
                ? "oklch(0.68 0.17 25)" : undefined,
            }}
            title={q.inventoryResult.error ?? q.inventoryResult.short_bands?.join(", ") ?? undefined}
          >
            inventario {relativeTime(q.inventoryResult.at)}:{" "}
            {q.inventoryResult.aborted
              ? "interrotto"
              : q.inventoryResult.complete === false
                ? "incompleto"
                : `${q.inventoryResult.removed ?? 0} spariti su ${q.inventoryResult.candidates ?? 0} candidati`}
          </span>
        )}
        {!!q.photoQueue && (
          <span>{q.photoQueue.toLocaleString("it-IT")} annunci con foto in download</span>
        )}
      </div>
      {q.latency && q.latency.published24h ? (
        <div style={{ display: "flex", gap: "18px", flexWrap: "wrap", fontSize: "12px" }}>
          <span style={head}>Ritardo</span>
          <span title="Dalla pubblicazione su Subito a quando l'abbiamo visto (annunci delle ultime 24h)">
            scoperta: mediana {q.latency.discoveryP50Min} min · 95% entro {q.latency.discoveryP95Min} min
          </span>
          <span
            style={{ color: q.latency.lateOver2h ? "oklch(0.78 0.14 80)" : undefined }}
            title="Scoperti oltre 2 ore dopo la pubblicazione: li ha recuperati l'inventario, non lo sweep"
          >
            {q.latency.lateOver2h} su {q.latency.published24h} scoperti dopo 2h
          </span>
          <span>
            alert:{" "}
            {q.latency.alerts7d
              ? `mediana ${q.latency.alertP50Min} min · 95% entro ${q.latency.alertP95Min} min`
              : "nessun alert inviato in 7 giorni"}
          </span>
        </div>
      ) : null}
      {q.backup && <BackupLine b={q.backup} head={head} />}
    </div>
  );
}

const BACKUP_STATE: Record<string, { label: string; color: string }> = {
  ok: { label: "ok", color: "var(--accent)" },
  vecchio: { label: "in ritardo", color: "oklch(0.78 0.14 80)" },
  fallito: { label: "fallito", color: "oklch(0.68 0.17 25)" },
  assente: { label: "mai eseguito", color: "oklch(0.68 0.17 25)" },
};

function BackupLine(props: { b: NonNullable<DataQuality["backup"]>; head: CSSProperties }) {
  const { b, head } = props;
  const st = BACKUP_STATE[b.state] ?? BACKUP_STATE.assente;
  return (
    <div style={{ display: "flex", gap: "18px", flexWrap: "wrap", fontSize: "12px" }}>
      <span style={head}>Backup</span>
      <span style={{ color: st.color, fontWeight: 700 }}>{st.label}</span>
      {b.at && <span>ultimo giro {relativeTime(b.at)}</span>}
      {b.restoredListings != null && (
        <span>ripristino di prova: {b.restoredListings.toLocaleString("it-IT")} annunci</span>
      )}
      {b.sizeKb != null && b.sizeKb > 0 && <span>dump {(b.sizeKb / 1024).toFixed(1)} MB</span>}
      {b.media && b.media.files >= 0 && (
        <span>foto {b.media.mirrored.toLocaleString("it-IT")}/{b.media.files.toLocaleString("it-IT")}</span>
      )}
      {b.error && <span style={{ color: "oklch(0.68 0.17 25)" }}>{b.error}</span>}
      {b.state === "assente" && (
        <span style={{ color: "oklch(0.6 0.01 250)" }}>avvia il servizio: docker compose up -d backup</span>
      )}
    </div>
  );
}

/** Cosa stanno correggendo le riparazioni registrate (E3). */
function RepairFeedbackLine(props: { fb: NonNullable<DealsSummary["repairFeedback"]> }) {
  const { fb } = props;
  const guasti = Object.entries(fb.guasti).filter(([g]) => g !== "sconosciuto");
  if (!fb.parts.length && !guasti.length) return null;
  return (
    <div style={{ flexBasis: "100%", fontSize: "12px", color: "oklch(0.65 0.01 250)", lineHeight: 1.7 }}>
      {fb.parts.map((p) => (
        <span key={`${p.part}:${p.source}`} style={{ marginRight: "16px" }}>
          {p.part} {p.source}: reale ×{p.ratio} del listino su {p.n}{" "}
          {p.applied ? <b style={{ color: "var(--accent)" }}>· applicato</b> : `· si applica da ${fb.minSamples}`}
        </span>
      ))}
      {guasti.map(([g, v]) => (
        <span key={g} style={{ marginRight: "16px" }}>
          {g}: {v.successPct ?? "—"}% riuscite su {v.n}
          {v.reliable ? "" : ` (pochi casi)`}
        </span>
      ))}
    </div>
  );
}

/** Quanto mercato abbiamo osservato, target per target. */
function TargetCoverageTable(props: { label: string; rows: TargetCoverage[] }) {
  const [open, setOpen] = useState(false);
  const { rows } = props;
  const totals = rows.reduce(
    (a, r) => ({
      active: a.active + r.active,
      sold: a.sold + r.sold,
      total: a.total + r.total,
      new24h: a.new24h + r.new24h,
    }),
    { active: 0, sold: 0, total: 0, new24h: 0 },
  );
  const maxTotal = Math.max(...rows.map((r) => r.total), 1);
  const head: CSSProperties = {
    fontSize: "10.5px", fontWeight: 700, color: "oklch(0.55 0.01 250)",
    textTransform: "uppercase", letterSpacing: "0.04em",
  };
  const cols = "1.5fr 0.7fr 0.7fr 0.8fr 1.4fr";
  return (
    <div style={{ border: "1px solid oklch(0.27 0.01 250)", borderRadius: "12px", overflow: "hidden" }}>
      <div
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", cursor: "pointer", background: "oklch(0.20 0.008 250)",
        }}
      >
        <div>
          <div style={{ fontSize: "14px", fontWeight: 700 }}>
            Copertura dati · {props.label}
          </div>
          <div style={{ fontSize: "12px", color: "oklch(0.6 0.01 250)", marginTop: "2px" }}>
            {rows.length} target · <b>{totals.total.toLocaleString("it-IT")}</b> annunci osservati in
            totale ({totals.active.toLocaleString("it-IT")} ora attivi,{" "}
            {totals.sold.toLocaleString("it-IT")} già spariti)
          </div>
        </div>
        <span style={{ color: "oklch(0.55 0.01 250)" }}>{open ? "▾" : "▸"}</span>
      </div>
      {open && (
        <>
          <div
            style={{
              display: "grid", gridTemplateColumns: cols, gap: "10px",
              padding: "8px 16px", background: "oklch(0.175 0.008 250)", ...head,
            }}
          >
            <div>Target</div>
            <div title="Annunci attivi adesso">Attivi</div>
            <div title="Annunci spariti: venduti o ritirati">Spariti</div>
            <div title="Totale annunci distinti mai osservati">Osservati</div>
            <div />
          </div>
          {rows.map((r) => (
            <div
              key={r.query}
              style={{
                display: "grid", gridTemplateColumns: cols, gap: "10px",
                padding: "8px 16px", alignItems: "center", fontSize: "12.5px",
                borderTop: "1px solid oklch(0.24 0.008 250)",
              }}
            >
              <div style={{ fontWeight: 600 }}>{r.query}</div>
              <div style={{ fontFamily: MONO }}>{r.active}</div>
              <div style={{ fontFamily: MONO, color: "oklch(0.6 0.01 250)" }}>{r.sold}</div>
              <div style={{ fontFamily: MONO, fontWeight: 700 }}>{r.total}</div>
              <div
                style={{
                  height: "6px", borderRadius: "3px", background: "oklch(0.24 0.008 250)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${(r.total / maxTotal) * 100}%`, height: "100%",
                    background: "var(--accent)",
                  }}
                />
              </div>
            </div>
          ))}
          <div
            style={{
              padding: "10px 16px", fontSize: "11.5px", color: "oklch(0.55 0.01 250)",
              borderTop: "1px solid oklch(0.24 0.008 250)", lineHeight: 1.6,
            }}
          >
            «Attivi» è una fotografia del momento e oscilla di continuo (ne entrano di
            nuovi, altri spariscono): per questo il totale in dashboard sale e scende.
            «Osservati» è cumulativo ed è il numero che conta per fidarsi delle statistiche
            di quel modello.
          </div>
        </>
      )}
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
