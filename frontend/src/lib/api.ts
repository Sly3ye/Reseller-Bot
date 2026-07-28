export type MarketTrendPoint = {
  month: string;
  price: number;
};

export type LiveOpportunity = {
  id: string;
  model: string;
  foundPrice: number;
  averagePrice: number;
  marginPercent: number;
  source: string;
  market: string;
  url: string;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Category = "smartphone" | "automobile";

export type PriceDrop = {
  oldPrice: number | null;
  newPrice: number | null;
  changedAt: string | null;
};

// E — Watch di prezzo: storico completo dei ribassi del singolo annuncio.
export type PriceWatch = {
  firstPrice: number | null;
  currentPrice: number | null;
  dropCount: number;
  totalDropEur: number | null;
  totalDropPct: number | null;
  lastDropAt: string | null;
  daysSinceLastDrop: number | null;
  motivation: "alto" | "medio" | "basso";
};

export type ScorePoint = { label: string; points: number };

export type SellerProfile = {
  active: number;
  sold: number;
  avgDaysToSell: number | null;
  dropRate: number;
  avgDropPct: number | null;
  type: string | null;
  motivated: boolean;
};

export type RepairInfo = {
  items: { defect: string; label: string; cost: number }[];
  total: number;
  netMarginEur: number | null;
  netMarginPct: number | null;
};

export type ApiOpportunity = {
  id: string;
  title: string | null;
  location: string | null;
  askingPrice: number | null;
  originalPrice: number | null;
  marketAvg: number | null;
  marginEur: number | null;
  marginPct: number | null;
  priceDrop: PriceDrop | null;
  priceWatch: PriceWatch | null;
  description: string | null;
  images: string[];
  foundAt: string | null;
  daysOnline: number | null;
  source: string | null;
  status: string | null;
  triage: "salvato" | "scartato" | null;
  url: string;
  // Segnale NLP + venditore
  sellerType: string | null;
  sellerActiveCount: number | null;
  sellerProfile: SellerProfile | null;
  defects: string[];
  urgencyFlags: string[];
  features: string[];
  // Verticale-specifici
  year: number | null;
  km: number | null;
  transmission: string | null;
  fuel: string | null;
  storageGb: number | null;
  batteryPct: number | null;
  expectedPrice: number | null;
  marginVsExpected: number | null;
  // Fase 1: variante canonica + condizione
  variantKey: string | null;
  conditionTier: string | null;
  color: string | null;
  // Fase 2: valutazione predittiva
  fairValue: number | null;
  pricePosition: number | null;
  marginVsFairEur: number | null;
  marginVsFairPct: number | null;
  dealClass: "affare" | "in-linea" | "caro" | "sospetto" | "n/d";
  // AI locale (Ollama): analisi semantica della descrizione (null se non processata)
  ai: {
    motivo_prezzo: string;
    categoria_motivo: string;
    riparabile: boolean;
    nota_riparazione: string;
    rischio_truffa: string;
    sintesi: string;
  } | null;
  // Deal Score + assistente trattativa
  score: number;
  scoreBreakdown: ScorePoint[];
  repair: RepairInfo | null;
  defectPenaltyEur: number | null;
  suggestedOffer: number | null;
  // Analitiche operative (compravendita)
  fairValueSource: "km" | "venduti" | "listati" | null;
  valuationSamples: number | null;
  valuationConfidence: "alta" | "media" | "bassa" | null;
  roiPerDayPct: number | null;
  maxBid: number | null;
  buyAtAsking: boolean;
  // Risk Score anti-frode (null = nessun segnale di rischio)
  risk: RiskInfo | null;
};

export type RiskInfo = {
  level: "alto" | "medio" | "basso";
  label: string;
  score: number;
  reasons: string[];
};

export type PriceBand = {
  band: string;
  priceFrom: number;
  priceTo: number;
  avgDays: number;
  count: number;
};

export type PriceBox = {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
};

export type AiDistribution = {
  analyzed: number;
  legittimo: number;
  difetto: number;
  sospetto: number;
  riparabili: number;
};

export type ApiModelStat = {
  name: string;
  avg: number | null;
  sample: number | null;
  changePct: number | null;
  series: { date: string; price: number }[];
  // A — analitiche dai listing attivi
  volume: number;
  medianActive: number | null;
  priceBox: PriceBox | null;
  marginPotentialPct: number | null;
  spreadEur: number | null;
  activeDeals: number;
  storagePremium: Record<string, number>;
  storageVolume: Record<string, number>;
  conditionImpact: Record<string, number>;
  sellers: number;
  fintoPrivato: number;
  ai: AiDistribution;
  // C — vendite reali
  avgDaysToSell: number | null;
  sampleSold: number | null;
  soldMedian: number | null;
  soldMax: number | null;
  priceBands: PriceBand[];
  sellThroughRate: number | null;
  // listati (fallback/confronto)
  fastSalePrice: number | null;
  maxSalePrice: number | null;
  // domanda/offerta (ultimi 7gg)
  inflow7d: number;
  outflow7d: number;
  demandIndex: number | null;
  // F — liquidità per variante (quanto in fretta gira / quanta domanda)
  liquidityScore: number | null;
  liquidityLevel: "alta" | "media" | "bassa" | null;
  // ranking
  roiPerDayPct: number | null;
  opportunityScore: number | null;
};

export type SellerRankRow = {
  sellerId: string;
  type: string | null;
  active: number;
  sold: number;
  avgDaysToSell: number | null;
  dropRate: number;
  avgDropPct: number | null;
  motivated: boolean;
  sampleTitle: string | null;
};

export type ApiTrends = {
  activeListings: number;
  avgMarketPrice: number | null;
  outliersFiltered: number | null;
  avgDaysToSell: number | null;
  topOpportunity: string | null;
  trend: { date: string; price: number }[];
  trendProduct: string | null;
  models: ApiModelStat[];
  sellers: SellerRankRow[];
};

export type DealStage =
  | "interessante"
  | "contattato"
  | "offerta"
  | "comprato"
  | "in_vendita"
  | "venduto"
  | "sfumato";

export type Deal = {
  id: string;
  listing_id: string | null;
  category: "smartphone" | "automobile";
  title: string | null;
  listing_url: string | null;
  stage: DealStage;
  asking_price: number | null;
  market_avg: number | null;
  offer_price: number | null;
  buy_price: number | null;
  extra_costs: { label: string; amount: number }[];
  sell_price: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // calcolati dal backend
  invested: number | null;
  extraCostsTotal: number;
  profit: number | null;
  realMarginPct: number | null;
  estimatedMarginEur: number | null;
  estimateErrorEur: number | null;
  heldDays: number | null;
  roiPerDayPct: number | null;
};

export type DealsSummary = {
  totalDeals: number;
  sold: number;
  openDeals: number;
  investedOpen: number;
  realizedProfit: number;
  avgRealMarginPct: number | null;
  // Feedback loop stima vs realtà
  avgEstimatedMarginEur: number | null;
  avgRealizedProfitEur: number | null;
  estimationBiasEur: number | null;
  estimationAccuracyPct: number | null;
  avgHeldDays: number | null;
  realizedRoiPerDayPct: number | null;
};

export type SortMode = "score" | "recent" | "margin" | "roi";
export type ViewMode = "attivi" | "salvati" | "tutti";
export type PresetMode = "compra_ora" | "motivati" | "riparabili";

export type OppFilters = {
  sort?: SortMode;
  model?: string | null;
  storage?: number | null;
  color?: string | null;
  condition?: string | null;
  dealClass?: string | null;
  minMargin?: number | null;
  q?: string | null;
  view?: ViewMode;
  preset?: PresetMode | null;
  limit?: number;
  offset?: number;
};

export type OpportunityFacets = {
  models: { key: string; label: string; count: number }[];
  storages: { value: number; count: number }[];
  colors: { value: string; count: number }[];
  conditions: { value: string; count: number }[];
};

export type OpportunitiesPage = {
  items: ApiOpportunity[];
  total: number;
  facets: OpportunityFacets;
};

export async function fetchOpportunities(
  category: Category,
  filters: OppFilters = {},
  signal?: AbortSignal,
): Promise<OpportunitiesPage> {
  const p = new URLSearchParams({ category });
  if (filters.sort) p.set("sort", filters.sort);
  if (filters.model) p.set("model", filters.model);
  if (filters.storage != null) p.set("storage", String(filters.storage));
  if (filters.color) p.set("color", filters.color);
  if (filters.condition) p.set("condition", filters.condition);
  if (filters.dealClass) p.set("deal_class", filters.dealClass);
  if (filters.minMargin != null) p.set("min_margin", String(filters.minMargin));
  if (filters.q) p.set("q", filters.q);
  if (filters.view) p.set("view", filters.view);
  if (filters.preset) p.set("preset", filters.preset);
  p.set("limit", String(filters.limit ?? 30));
  p.set("offset", String(filters.offset ?? 0));

  const res = await fetch(`${API_BASE_URL}/api/opportunities?${p.toString()}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/opportunities failed (${res.status})`);
  return res.json();
}

export async function fetchTrends(
  category: Category,
  signal?: AbortSignal,
): Promise<ApiTrends> {
  const res = await fetch(`${API_BASE_URL}/api/trends?category=${category}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/trends failed (${res.status})`);
  return res.json();
}

// Curva di deprezzamento: prezzo mediano in funzione dell'età del modello.
export type DepreciationPoint = {
  modelKey: string;
  model: string;
  line: string;
  lineLabel: string;
  storage: number | null;
  storageLabel: string;
  ageYears: number;
  releasedAt: string;
  median: number;
  sample: number;
  retentionPct: number | null;
  loss12mEur: number | null;
  loss12mPct: number | null;
  carryCostMonthEur: number | null;
  vsModel: string | null;
};

export type DepreciationCurve = {
  line: string;
  lineLabel: string;
  storage: number | null;
  storageLabel: string;
  points: DepreciationPoint[];
  sample: number;
};

export type DepreciationData = {
  supported: boolean;
  asOf?: string;
  storages: number[];
  curves: DepreciationCurve[];
  models: DepreciationPoint[];
  summary: {
    best: { model: string; storageLabel: string; loss12mPct: number } | null;
    worst: { model: string; storageLabel: string; loss12mPct: number } | null;
    avgLoss12mPct: number | null;
  };
};

export async function fetchDepreciation(
  category: Category,
  signal?: AbortSignal,
): Promise<DepreciationData> {
  const res = await fetch(`${API_BASE_URL}/api/depreciation?category=${category}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/depreciation failed (${res.status})`);
  return res.json();
}

// Tempo di vendita: fatti grezzi dei venduti da incrociare in UI.
export type TimeToSaleRecord = {
  model: string;
  color: string | null;
  storageGb: number | null;
  days: number;
  price: number | null;
};

export type TimeToSaleData = {
  records: TimeToSaleRecord[];
  models: string[];
  colors: string[];
  storages: number[];
  sampleSold: number;
};

export async function fetchTimeToSale(
  category: Category,
  signal?: AbortSignal,
): Promise<TimeToSaleData> {
  const res = await fetch(`${API_BASE_URL}/api/time-to-sale?category=${category}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/time-to-sale failed (${res.status})`);
  return res.json();
}

export async function fetchDeals(signal?: AbortSignal): Promise<Deal[]> {
  const res = await fetch(`${API_BASE_URL}/api/deals`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/deals failed (${res.status})`);
  return res.json();
}

export async function fetchDealsSummary(
  signal?: AbortSignal,
): Promise<DealsSummary> {
  const res = await fetch(`${API_BASE_URL}/api/deals/summary`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/deals/summary failed (${res.status})`);
  return res.json();
}

export async function createDeal(payload: {
  category: "smartphone" | "automobile";
  listing_id?: string;
  title?: string;
  listing_url?: string;
  asking_price?: number;
  market_avg?: number;
  offer_price?: number;
}): Promise<Deal> {
  const res = await fetch(`${API_BASE_URL}/api/deals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`POST /api/deals failed (${res.status})`);
  return res.json();
}

export async function updateDeal(
  id: string,
  patch: Partial<
    Pick<
      Deal,
      "stage" | "offer_price" | "buy_price" | "sell_price" | "extra_costs" | "notes"
    >
  >,
): Promise<Deal> {
  const res = await fetch(`${API_BASE_URL}/api/deals/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`PATCH /api/deals/${id} failed (${res.status})`);
  return res.json();
}

export async function deleteDeal(id: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/deals/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`DELETE /api/deals/${id} failed (${res.status})`);
}

export async function patchOpportunityStatus(
  id: string,
  category: Category,
  status: "nuovo" | "visto" | "scaduto" | "venduto_rimosso",
): Promise<void> {
  const res = await fetch(
    `${API_BASE_URL}/api/opportunities/${id}?category=${category}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    },
  );
  if (!res.ok)
    throw new Error(`PATCH /api/opportunities/${id} failed (${res.status})`);
}

export async function setTriage(
  id: string,
  category: Category,
  triage: "salvato" | "scartato" | null,
): Promise<void> {
  const res = await fetch(
    `${API_BASE_URL}/api/opportunities/${id}/triage?category=${category}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ triage }),
    },
  );
  if (!res.ok)
    throw new Error(`PATCH /api/opportunities/${id}/triage failed (${res.status})`);
}

/* --------------------------------------------------------- Salute scraper */

export type ScrapeRun = {
  status: "ok" | "degraded" | "down" | "idle";
  targets: number;
  ok: number;
  failed: number;
  scraped: number;
  new_count: number;
  ran_at: string;
};

export type Coverage = {
  activeTargets: number | null;
  activeListings: number | null;
  new24h: number;
};

export type ScraperHealth = {
  proxy_configured: boolean;
  impersonate_pool: string[];
  scraper: Record<string, ScrapeRun | null>;
  recent: Record<string, ScrapeRun[]>;
  coverage: Record<string, Coverage>;
};

export async function fetchScraperHealth(
  signal?: AbortSignal,
): Promise<ScraperHealth> {
  const res = await fetch(`${API_BASE_URL}/health/scraper`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /health/scraper failed (${res.status})`);
  return res.json();
}

/* ------------------------------------------------------------- Impostazioni */

export type AppSettings = {
  alert_min_margin_pct: number;
  alert_min_drop_pct: number;
  alert_min_score: number;
  target_margin_pct: Record<string, number>;
  apple_part_eur: Record<string, Record<string, number>>;
  telegram_chat_tech: string | null;
  telegram_chat_auto: string | null;
  telegram_chat_ops: string | null;
};

export async function fetchSettings(signal?: AbortSignal): Promise<AppSettings> {
  const res = await fetch(`${API_BASE_URL}/api/settings`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/settings failed (${res.status})`);
  return res.json();
}

export async function updateSettings(
  values: Partial<AppSettings>,
): Promise<AppSettings> {
  const res = await fetch(`${API_BASE_URL}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error(`PUT /api/settings failed (${res.status})`);
  return res.json();
}

/* --------------------------------------------------- Automations (scheduler) */

export type AutomationJob = {
  id: string;
  name: string;
  kind: "interval" | "cron";
  intervalMinutes: number | null;
  trigger: string;
  nextRun: string | null;
  paused: boolean;
  category: string | null;
};

export type AutomationsState = {
  running: boolean;
  jobs: AutomationJob[];
};

export async function fetchAutomations(
  signal?: AbortSignal,
): Promise<AutomationsState> {
  const res = await fetch(`${API_BASE_URL}/api/automations`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/automations failed (${res.status})`);
  return res.json();
}

async function _automationAction(
  id: string,
  action: "run" | "pause" | "resume",
): Promise<AutomationJob> {
  const res = await fetch(`${API_BASE_URL}/api/automations/${id}/${action}`, {
    method: "POST",
  });
  if (!res.ok)
    throw new Error(`POST /api/automations/${id}/${action} failed (${res.status})`);
  return (await res.json()).job;
}

export const runAutomation = (id: string) => _automationAction(id, "run");
export const pauseAutomation = (id: string) => _automationAction(id, "pause");
export const resumeAutomation = (id: string) => _automationAction(id, "resume");

export async function rescheduleAutomation(
  id: string,
  minutes: number,
): Promise<AutomationJob> {
  const res = await fetch(`${API_BASE_URL}/api/automations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes }),
  });
  if (!res.ok) throw new Error(`PATCH /api/automations/${id} failed (${res.status})`);
  return (await res.json()).job;
}

export async function getMarketTrends(): Promise<MarketTrendPoint[]> {
  void API_BASE_URL;

  return [
    { month: "Feb", price: 555 },
    { month: "Mar", price: 535 },
    { month: "Apr", price: 515 },
    { month: "May", price: 498 },
    { month: "Jun", price: 482 },
    { month: "Jul", price: 468 },
  ];
}

export async function getLiveOpportunities(): Promise<LiveOpportunity[]> {
  void API_BASE_URL;

  return [
    {
      id: "opp-iphone-13-pro-001",
      model: "iPhone 13 Pro 128GB",
      foundPrice: 395,
      averagePrice: 520,
      marginPercent: 24,
      source: "Subito",
      market: "iPhone",
      url: "https://www.subito.it/",
    },
    {
      id: "opp-panda-001",
      model: "Fiat Panda 1.2 Lounge",
      foundPrice: 5300,
      averagePrice: 6650,
      marginPercent: 20,
      source: "Subito",
      market: "Auto",
      url: "https://www.subito.it/",
    },
    {
      id: "opp-iphone-14-001",
      model: "iPhone 14 128GB",
      foundPrice: 485,
      averagePrice: 610,
      marginPercent: 18,
      source: "Marketplace",
      market: "iPhone",
      url: "https://www.subito.it/",
    },
    {
      id: "opp-bmw-001",
      model: "BMW Serie 1 116d",
      foundPrice: 9800,
      averagePrice: 11800,
      marginPercent: 17,
      source: "Subito",
      market: "Auto",
      url: "https://www.subito.it/",
    },
  ];
}
