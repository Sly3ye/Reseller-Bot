"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import {
  createDeal,
  deleteDeal,
  fetchDeals,
  fetchDealsSummary,
  fetchOpportunities,
  fetchTrends,
  patchOpportunityStatus,
  updateDeal,
  type ApiOpportunity,
  type ApiTrends,
  type Category,
  type Deal,
  type DealStage,
  type DealsSummary,
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
type Screen = "sniper" | "intel" | "pipeline" | "automations";
type MarginFilter = "all" | "high";
type SortMode = "recent" | "score";

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
  const [search, setSearch] = useState("");
  const [marginFilter, setMarginFilter] = useState<MarginFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("score");

  const [opportunities, setOpportunities] = useState<ApiOpportunity[]>([]);
  const [intel, setIntel] = useState<ApiTrends | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [batchRunning, setBatchRunning] = useState(false);
  const [batchLastRun, setBatchLastRun] = useState("03:00 (today)");
  const [sniperInterval, setSniperInterval] = useState<15 | 30 | 60>(30);
  const [telegramEnabled, setTelegramEnabled] = useState(true);
  const [secondsToNextScan, setSecondsToNextScan] = useState(812);

  const [deals, setDeals] = useState<Deal[]>([]);
  const [dealsSummary, setDealsSummary] = useState<DealsSummary | null>(null);
  const [pipelineIds, setPipelineIds] = useState<Set<string>>(new Set());

  // Il toggle mostra "Auto", ma il backend usa la categoria nativa "automobile".
  const category: Category = vertical === "tech" ? "smartphone" : "automobile";

  // Fetch the feed + market intelligence whenever the business vertical changes.
  useEffect(() => {
    const controller = new AbortController();

    // I reset di stato sono in un microtask: evita il setState sincrono nel
    // corpo dell'effect (cascading render) mantenendo lo stesso comportamento.
    void Promise.resolve().then(() => {
      if (controller.signal.aborted) return;
      setLoading(true);
      setError(null);
      setExpandedId(null);
    });

    Promise.all([
      fetchOpportunities(category, controller.signal),
      fetchTrends(category, controller.signal),
    ])
      .then(([opps, trends]) => {
        setOpportunities(opps);
        setIntel(trends);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Errore di caricamento");
        setOpportunities([]);
        setIntel(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [category]);

  useEffect(() => {
    const tick = setInterval(() => {
      setSecondsToNextScan((s) => (s > 0 ? s - 1 : sniperInterval * 60));
    }, 1000);
    return () => clearInterval(tick);
  }, [sniperInterval]);

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

  const toggleVertical = () => setVertical((v) => (v === "tech" ? "auto" : "tech"));

  const isTech = vertical === "tech";
  const accent = isTech ? "oklch(0.62 0.19 265)" : "oklch(0.68 0.19 45)";
  const accentSoft = isTech ? "oklch(0.62 0.19 265 / 0.16)" : "oklch(0.68 0.19 45 / 0.16)";
  const accentBorder = isTech ? "oklch(0.62 0.19 265 / 0.4)" : "oklch(0.68 0.19 45 / 0.4)";
  const accentText = isTech ? "oklch(0.80 0.13 265)" : "oklch(0.82 0.14 45)";

  const filteredListings = useMemo(() => {
    let list = opportunities;
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (it) =>
          (it.title ?? "").toLowerCase().includes(q) ||
          (it.location ?? "").toLowerCase().includes(q),
      );
    }
    if (marginFilter === "high") {
      list = list.filter((it) => it.marginPct !== null && it.marginPct >= 20);
    }
    if (sortMode === "score") {
      list = [...list].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    }
    return list;
  }, [opportunities, search, marginFilter, sortMode]);

  const hasResults = filteredListings.length > 0;

  const trendValues = useMemo(
    () => (intel?.trend ?? []).map((p) => p.price),
    [intel],
  );
  const trendPaths = useMemo(() => buildTrendPaths(trendValues), [trendValues]);

  const mm = Math.floor(secondsToNextScan / 60);
  const ss = secondsToNextScan % 60;
  const nextScanLabel = `${mm}:${String(ss).padStart(2, "0")}`;

  const forceRunBatch = () => {
    if (batchRunning) return;
    setBatchRunning(true);
    setTimeout(() => {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mn = String(now.getMinutes()).padStart(2, "0");
      setBatchRunning(false);
      setBatchLastRun(`${hh}:${mn} (today)`);
    }, 2200);
  };

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
              resultCount={filteredListings.length}
              category={category}
              search={search}
              onSearchChange={setSearch}
              marginFilter={marginFilter}
              onFilterChange={setMarginFilter}
              sortMode={sortMode}
              onSortChange={setSortMode}
              loading={loading}
              error={error}
              hasResults={hasResults}
              listings={filteredListings}
              expandedId={expandedId}
              flaggedIds={flaggedIds}
              pipelineIds={pipelineIds}
              onToggleExpand={(id) => {
                setExpandedId((cur) => (cur === id ? null : id));
                const item = filteredListings.find((x) => x.id === id);
                if (item && expandedId !== id) markSeen(item);
              }}
              onToggleFlag={(id) => setFlaggedIds((cur) => ({ ...cur, [id]: !cur[id] }))}
              onAddToPipeline={addToPipeline}
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

          {screen === "automations" && (
            <AutomationsScreen
              batchRunning={batchRunning}
              batchLastRun={batchLastRun}
              onForceRun={forceRunBatch}
              sniperInterval={sniperInterval}
              onSetInterval={setSniperInterval}
              telegramEnabled={telegramEnabled}
              onToggleTelegram={() => setTelegramEnabled((v) => !v)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- shared */

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

const GRID_COLUMNS = "56px 60px 2.1fr 1fr 1fr 1.1fr 84px 54px";

function SniperScreen(props: {
  resultCount: number;
  category: Category;
  search: string;
  onSearchChange: (v: string) => void;
  marginFilter: MarginFilter;
  onFilterChange: (v: MarginFilter) => void;
  sortMode: SortMode;
  onSortChange: (v: SortMode) => void;
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
}) {
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
          <div style={{ fontSize: "22px", fontWeight: 700 }}>Live Sniper Feed</div>
          <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
            {props.resultCount} opportunities · scraped continuously from classified listings
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
            {(["score", "recent"] as SortMode[]).map((mode) => (
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
                {mode === "score" ? "Deal Score" : "Recenti"}
              </div>
            ))}
          </div>
        </div>
      </div>

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
            Try clearing the search or margin filter
          </div>
        </div>
      )}
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
        <div
          onClick={(e) => {
            e.stopPropagation();
            props.onFlag();
          }}
          title="Flag as scam/error"
          style={{
            width: "30px",
            height: "30px",
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
                  <a
                    key={item.id + "-" + i}
                    href={src}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      minWidth: "140px",
                      width: "140px",
                      height: "100px",
                      borderRadius: "8px",
                      flexShrink: 0,
                      overflow: "hidden",
                      border: "1px solid oklch(0.32 0.01 250)",
                      display: "block",
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={src}
                      alt={`foto ${i + 1}`}
                      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                    />
                  </a>
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

  const stats: { label: string; value: string; hint?: string; color?: string }[] = [];
  if (item.fairValue !== null) {
    stats.push({
      label: "Valore equo stimato",
      value: eur(item.fairValue),
      hint:
        item.marginVsFairPct !== null
          ? `${item.marginVsFairPct >= 0 ? "+" : ""}${item.marginVsFairPct}% vs richiesto` +
            (item.pricePosition !== null
              ? ` · più economico del ${Math.round(100 - item.pricePosition)}%`
              : "")
          : undefined,
      color:
        item.dealClass === "affare"
          ? "oklch(0.75 0.15 150)"
          : item.dealClass === "sospetto"
            ? "oklch(0.75 0.17 30)"
            : "var(--accent-text)",
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
    stats.push({
      label: "Venditore",
      value: label,
      hint:
        item.sellerActiveCount != null
          ? `${item.sellerActiveCount} annunci attivi`
          : undefined,
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
      hint: `riparazione stimata ${eur(item.repair.total)}`,
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px" }}>
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
                media IQR-pulita sui modelli tracciati
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
                giorni medi found→venduto (time-to-sale)
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
                gridTemplateColumns: "1.8fr 1fr 0.8fr 0.9fr 1fr 1.2fr",
                gap: "12px",
                padding: "10px 20px",
                background: "oklch(0.20 0.008 250)",
                fontSize: "11px",
                fontWeight: 600,
                color: "oklch(0.46 0.01 250)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              <div>Modello</div>
              <div>Prezzo medio</div>
              <div>Campione</div>
              <div title="Variazione a 7 giorni">7g</div>
              <div title="Giorni medi found→venduto">Liquidità</div>
              <div title="Prezzo per vendita rapida / prezzo pieno">Rivendita</div>
            </div>
            {(intel?.models ?? []).length === 0 ? (
              <div style={{ padding: "16px 20px", fontSize: "13px", color: "oklch(0.46 0.01 250)" }}>
                {props.loading ? "Caricamento…" : "Nessun dato di mercato per questa categoria."}
              </div>
            ) : (
              (intel?.models ?? []).map((m) => {
                const positive = (m.changePct ?? 0) >= 0;
                return (
                  <div
                    key={m.name}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.8fr 1fr 0.8fr 0.9fr 1fr 1.2fr",
                      gap: "12px",
                      padding: "12px 20px",
                      borderTop: "1px solid oklch(0.24 0.008 250)",
                      alignItems: "center",
                      fontSize: "13px",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{m.name}</div>
                    <div style={{ fontFamily: MONO }}>{m.avg != null ? eur(m.avg) : "—"}</div>
                    <div style={{ fontFamily: MONO, color: "oklch(0.46 0.01 250)" }}>{m.sample ?? "—"}</div>
                    <div
                      style={{
                        fontFamily: MONO,
                        fontWeight: 600,
                        color:
                          m.changePct == null
                            ? "oklch(0.46 0.01 250)"
                            : positive
                              ? "oklch(0.72 0.16 150)"
                              : "oklch(0.68 0.19 25)",
                      }}
                    >
                      {m.changePct == null ? "—" : (positive ? "+" : "") + m.changePct + "%"}
                    </div>
                    <div style={{ fontFamily: MONO }}>
                      {m.avgDaysToSell != null ? (
                        <>
                          {m.avgDaysToSell}gg
                          <span style={{ fontSize: "10px", color: "oklch(0.46 0.01 250)", marginLeft: "3px" }}>
                            ({m.sampleSold ?? 0})
                          </span>
                        </>
                      ) : (
                        <span style={{ color: "oklch(0.46 0.01 250)" }}>—</span>
                      )}
                    </div>
                    <div style={{ fontFamily: MONO, fontSize: "12px" }}>
                      {m.fastSalePrice != null && m.maxSalePrice != null ? (
                        <>
                          <span style={{ color: "oklch(0.72 0.16 150)" }}>{eur(m.fastSalePrice)}</span>
                          <span style={{ color: "oklch(0.46 0.01 250)" }}> / {eur(m.maxSalePrice)}</span>
                        </>
                      ) : (
                        <span style={{ color: "oklch(0.46 0.01 250)" }}>—</span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ AUTOMATIONS */

function AutomationsScreen(props: {
  batchRunning: boolean;
  batchLastRun: string;
  onForceRun: () => void;
  sniperInterval: 15 | 30 | 60;
  onSetInterval: (v: 15 | 30 | 60) => void;
  telegramEnabled: boolean;
  onToggleTelegram: () => void;
}) {
  const panel: CSSProperties = {
    background: "oklch(0.19 0.008 250)",
    border: "1px solid oklch(0.27 0.01 250)",
    borderRadius: "12px",
    padding: "22px",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  };

  const intervalOption = (value: 15 | 30 | 60, label: string) => {
    const active = props.sniperInterval === value;
    return (
      <div
        onClick={() => props.onSetInterval(value)}
        style={{
          padding: "7px 16px",
          borderRadius: "6px",
          fontSize: "12.5px",
          fontWeight: 600,
          cursor: "pointer",
          background: active ? "var(--accent)" : "transparent",
          color: active ? "oklch(0.12 0.008 250)" : "oklch(0.62 0.01 250)",
        }}
      >
        {label}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", animation: "fadeIn 0.2s ease" }}>
      <div>
        <div style={{ fontSize: "22px", fontWeight: 700 }}>Automations &amp; Alerts</div>
        <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", marginTop: "4px" }}>
          Control panel for the backend schedulers
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        <div style={panel}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: "15px", fontWeight: 700 }}>Nightly Batch Engine</div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "4px 10px",
                borderRadius: "20px",
                background: props.batchRunning ? "oklch(0.72 0.16 150 / 0.14)" : "oklch(0.46 0.01 250 / 0.14)",
              }}
            >
              <div
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  background: props.batchRunning ? "oklch(0.72 0.16 150)" : "oklch(0.62 0.01 250)",
                  animation: props.batchRunning ? "pulseDot 1s ease-in-out infinite" : "none",
                }}
              />
              <div
                style={{
                  fontSize: "12px",
                  fontWeight: 700,
                  color: props.batchRunning ? "oklch(0.72 0.16 150)" : "oklch(0.62 0.01 250)",
                }}
              >
                {props.batchRunning ? "Running" : "Idle"}
              </div>
            </div>
          </div>
          <div style={{ fontSize: "13px", color: "oklch(0.62 0.01 250)", lineHeight: 1.6 }}>
            Recomputes market averages via IQR-cleaned nightly aggregation across all tracked categories.
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 14px",
              background: "oklch(0.16 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "8px",
            }}
          >
            <div style={{ fontSize: "12.5px", color: "oklch(0.46 0.01 250)" }}>Last run</div>
            <div style={{ fontFamily: MONO, fontSize: "13px", fontWeight: 600 }}>{props.batchLastRun}</div>
          </div>
          <div
            onClick={props.onForceRun}
            style={{
              alignSelf: "flex-start",
              padding: "10px 18px",
              borderRadius: "8px",
              background: "var(--accent)",
              color: "oklch(0.12 0.008 250)",
              fontSize: "13px",
              fontWeight: 700,
              cursor: "pointer",
              opacity: props.batchRunning ? 0.6 : 1,
            }}
          >
            {props.batchRunning ? "Running…" : "Force Run"}
          </div>
        </div>

        <div style={panel}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: "15px", fontWeight: 700 }}>Sniper Engine</div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "4px 10px",
                borderRadius: "20px",
                background: "oklch(0.72 0.16 150 / 0.14)",
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
              <div style={{ fontSize: "12px", fontWeight: 700, color: "oklch(0.72 0.16 150)" }}>Running</div>
            </div>
          </div>
          <div>
            <div style={{ fontSize: "12.5px", color: "oklch(0.46 0.01 250)", marginBottom: "8px" }}>Scan interval</div>
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
              {intervalOption(15, "15m")}
              {intervalOption(30, "30m")}
              {intervalOption(60, "1h")}
            </div>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "12px 14px",
              background: "oklch(0.16 0.008 250)",
              border: "1px solid oklch(0.27 0.01 250)",
              borderRadius: "8px",
            }}
          >
            <div>
              <div style={{ fontSize: "13px", fontWeight: 600 }}>Telegram alerts</div>
              <div style={{ fontSize: "11.5px", color: "oklch(0.46 0.01 250)", marginTop: "2px" }}>
                Notify webhook when margin &gt; 20%
              </div>
            </div>
            <div
              onClick={props.onToggleTelegram}
              style={{
                width: "42px",
                height: "24px",
                borderRadius: "12px",
                background: props.telegramEnabled ? "var(--accent)" : "oklch(0.32 0.01 250)",
                position: "relative",
                cursor: "pointer",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  position: "absolute",
                  top: "2px",
                  left: props.telegramEnabled ? "20px" : "2px",
                  width: "20px",
                  height: "20px",
                  borderRadius: "50%",
                  background: "white",
                  transition: "left 0.18s ease",
                }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
