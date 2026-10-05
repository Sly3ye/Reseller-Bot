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
  /** Rialzi dopo la pubblicazione (venditore senza fretta). */
  riseCount?: number;
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

export type RepairQuote = {
  defect: string;
  part: string;
  label: string;
  /** Ricambio originale Apple (Self Service Repair): prezzo, credito di reso, netto. */
  apple: { price: number; credit: number; net: number } | null;
  /** Ricambio aftermarket consigliato (qualità: soft oled, incell, deji...). */
  aftermarket: { price: number; grade: string; name: string } | null;
  /** Colonna usata nei conti: "aftermarket" | "apple" | "apple-fascia" (ripiego). */
  source: string | null;
  labor: number;
  /** Ricambio da listino, e ricambio corretto dalle tue riparazioni (E3). */
  listCost?: number | null;
  partCost?: number | null;
  correction?: { ratio: number; n: number } | null;
  cost: number;
};

/** Esito delle TUE riparazioni con un guasto dell'annuncio (E3). */
export type RepairTrackRecord = {
  guasto: string;
  n: number;
  successPct: number | null;
  riuscita: number;
  parziale: number;
  fallita: number;
};

export type RepairInfo = {
  items: RepairQuote[];
  /** Rivendita del telefono riparato (sano × sconto per ricambi non originali). */
  resaleAfterRepair?: number | null;
  resaleFactor?: number;
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
  /** Segnali dell'annuncio stesso (storia in listing_events): riposizionamenti,
   *  ribassi, ripubblicazioni, giorni online senza ribassi. Solo nella pagina. */
  signals?: {
    bumps30: number; lastBumpAt: string | null; drops: number; relisted: number;
    reasons: string[]; level: "alta" | "media" | null;
  } | null;
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
  fairValueSource: "eta-km" | "venduti" | "listati" | null;
  /** Auto: errore tipico del modello età+km della generazione (%). */
  fairValueErrPct?: number | null;
  /** Auto: il modello di prezzo della generazione (campione, deprezzamento). */
  carModel?: {
    n: number; errPct: number;
    /** null = dentro la generazione l'anno non sposta il prezzo a parità di km. */
    perYearPct: number | null;
    per10kKmPct: number;
    /** Premio coupé/cabrio sulla berlina, se misurato. */
    coupePct?: number | null;
    /** "generazione" = modello della sola generazione; "modello" = ripiego su tutte. */
    level?: "generazione" | "modello";
    yearRange: [number, number]; kmRange: [number, number];
  } | null;
  valuationSamples: number | null;
  valuationConfidence: "alta" | "media" | "bassa" | null;
  roiPerDayPct: number | null;
  /** Euro attesi per ora di lavoro: margine netto ÷ (viaggio + incontro +
   *  riparazione + vendita), con le probabilità solo se misurate. */
  profitPerHour?: {
    eurPerHour: number; hours: number; marginEur: number; expectedEur: number;
    minutes: { travel: number; meet: number; repair: number; sell: number; extra: number };
    distanceKnown: boolean; pRepair: number | null; pAvailable: number | null;
  } | null;
  maxBid: number | null;
  repairTrackRecord?: RepairTrackRecord | null;
  /** Auto: costi d'acquisto (passaggio, agenzia, preparazione) e margine netto. */
  acquisitionCosts?: {
    kw: number | null; kwEstimated: boolean; ipt: number | null; iptProvincePct: number;
    fees: number; agency: number; prep: number; transfer: number | null; total: number | null;
    carry?: { days: number; depreciation: number; fixed: number; total: number } | null;
  } | null;
  netMarginAfterCostsEur?: number | null;
  /** Distanza in linea d'aria dal comune di casa (Impostazioni). */
  distanceKm?: number | null;
  /** Auto: cosa controllare prima di comprarla (regole generali). */
  checklist?: { what: string; why: string }[];
  province?: string | null;
  // Costo di magazzino: deprezzamento maturato mentre resta invenduto,
  // già scontato dal maxBid.
  carryCost: {
    monthEur: number;
    holdDays: number;
    totalEur: number;
    estimatedDays: boolean;
  } | null;
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
  /** Media dei soli venduti: ottimista (chi resta online non conta). */
  avgDaysToSell: number | null;
  /** Kaplan–Meier (attivi come censurati): giorni entro cui si vende metà. null =
   * meno di metà venduta nella finestra osservata. */
  daysToSellKM?: number | null;
  sold7dPct?: number | null;
  sold30dPct?: number | null;
  /** Natura stimata delle sparizioni: venduto / ritirato / scaduto. */
  removalKinds?: Record<string, number>;
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
  /** Stima del bot fotografata all'aggancio (migrazione 20). */
  estimate: DealEstimate | null;
  /** Riparazione vera: pezzi montati, minuti, esito. */
  repair: DealRepair | null;
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
  repairCost: number | null;
  repairCostEstimated: number | null;
  repairCostErrorEur: number | null;
  repairOutcome: RepairOutcome | null;
  repairMinutes: number | null;
  // Tempo-in-stadio + allerta sugli affari fermi (con il deprezzamento
  // maturato sui pezzi già comprati).
  daysInStage: number | null;
  ageDays: number | null;
  stale: {
    days: number;
    limit: number;
    level: "attenzione" | "critico";
    hint: string;
    carryLossEur: number | null;
  } | null;
};

export type RepairOutcome = "riuscita" | "parziale" | "fallita";

export type DealEstimate = {
  kind: "riparazione" | "rivendita";
  marginEur: number | null;
  repairItems?: { part: string; source: string | null; cost: number }[];
  resaleAfterRepair?: number | null;
  maxBid?: number | null;
  /** Auto: costi d'acquisto stimati all'aggancio (passaggio, magazzino...). */
  acquisition?: ApiOpportunity["acquisitionCosts"];
};

export type DealRepair = {
  parts: { part: string; source: "aftermarket" | "apple" | "usato"; cost: number }[];
  minutes?: number | null;
  outcome?: RepairOutcome | null;
  notes?: string;
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
  // Affari fermi oltre soglia e costo del deprezzamento che stanno accumulando.
  staleDeals: number;
  staleCriticalDeals: number;
  staleCarryLossEur: number | null;
  repairs?: number;
  repairOutcomes?: Record<RepairOutcome, number>;
  repairSuccessPct?: number | null;
  repairCostBiasEur?: number | null;
  avgRepairMinutes?: number | null;
  repairFeedback?: {
    minSamples: number;
    parts: { part: string; source: string; n: number; ratio: number; applied: boolean }[];
    guasti: Record<string, { n: number; successPct: number | null; reliable: boolean }>;
  };
};

export type SortMode = "score" | "recent" | "margin" | "roi" | "distance" | "per_hour";
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
  minPrice?: number | null;
  maxPrice?: number | null;
  minDays?: number | null;
  maxDays?: number | null;
  q?: string | null;
  view?: ViewMode;
  preset?: PresetMode | null;
  /** Guasto NLP (es. "schermo-rotto"); onlyDefect = solo quel guasto. */
  defect?: string | null;
  onlyDefect?: boolean;
  limit?: number;
  offset?: number;
} & CarFilters;

/** Filtri del verticale auto (ignorati sugli iPhone). */
export type CarFilters = {
  minYear?: number | null;
  maxYear?: number | null;
  maxKm?: number | null;
  transmission?: string | null;
  fuel?: string | null;
  /** Variante modello@generazione, es. "bmw-125i@f2x". */
  generation?: string | null;
  brand?: string | null;
  /** Modello (marca-modello, es. "bmw-serie-1"): sostituisce il filtro modello. */
  model?: string | null;
};

export type OpportunityFacets = {
  models: { key: string; label: string; count: number; brand?: string }[];
  brands?: { value: string; count: number }[];
  storages: { value: number; count: number }[];
  colors: { value: string; count: number }[];
  conditions: { value: string; count: number }[];
  // Solo auto
  generations?: { value: string; label: string; count: number; model?: string }[];
  transmissions?: { value: string; count: number }[];
  fuels?: { value: string; count: number }[];
  yearRange?: [number, number] | null;
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
  if (filters.minPrice != null) p.set("min_price", String(filters.minPrice));
  if (filters.maxPrice != null) p.set("max_price", String(filters.maxPrice));
  if (filters.minDays != null) p.set("min_days", String(filters.minDays));
  if (filters.maxDays != null) p.set("max_days", String(filters.maxDays));
  if (filters.q) p.set("q", filters.q);
  if (filters.view) p.set("view", filters.view);
  if (filters.preset) p.set("preset", filters.preset);
  if (filters.minYear != null) p.set("min_year", String(filters.minYear));
  if (filters.maxYear != null) p.set("max_year", String(filters.maxYear));
  if (filters.maxKm != null) p.set("max_km", String(filters.maxKm));
  if (filters.transmission) p.set("transmission", filters.transmission);
  if (filters.fuel) p.set("fuel", filters.fuel);
  if (filters.generation) p.set("generation", filters.generation);
  if (filters.brand) p.set("brand", filters.brand);
  if (filters.defect) {
    p.set("defect", filters.defect);
    if (filters.onlyDefect) p.set("only_defect", "true");
  }
  p.set("limit", String(filters.limit ?? 30));
  p.set("offset", String(filters.offset ?? 0));

  const res = await fetch(`${API_BASE_URL}/api/opportunities?${p.toString()}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /api/opportunities failed (${res.status})`);
  return res.json();
}

export type RepairScenario = {
  partCost: number;
  grade?: string;
  resale: number;
  resaleRatio: number;
  margin: number;
  marginAtGoodBuy: number | null;
  roiPct: number | null;
};

export type RepairCell = {
  model: string;
  modelKey: string | null;
  defect: string;
  defectLabel: string;
  part?: string;
  listings: number;
  weekly: number;
  goodDealsWeekly: number;
  fragile: boolean;
  healthyMedian: number;
  healthySamples: number;
  buyMedian: number;
  buyGood: number | null;
  discountEur: number;
  scenarios: { aftermarket?: RepairScenario; apple?: RepairScenario };
  best: (RepairScenario & { source: "aftermarket" | "apple" }) | null;
  weeklyPotentialEur: number | null;
  /** Sconto rotto/sano per taglio di memoria e media pesata sul mix dei rotti. */
  byStorage?: { storage: number; listings: number; healthySamples: number;
    buyMedian: number; healthyMedian: number; discountEur: number }[];
  discountSameStorageEur?: number | null;
  /** Prezzo del sano usato nei conti (a parità di memoria dei rotti se possibile). */
  healthyRef?: number;
  healthyRefSameStorage?: boolean;
};

export type RepairMatrix = {
  cells: RepairCell[];
  nonOriginalRatios: Record<string, { ratio: number; models: number; samples: number; measured: boolean }>;
  windowDays: number;
  computedAt: string;
};

/** Auto: matrice "dove cacciare" per modello@generazione. */
export type CarHuntCell = {
  variantKey: string;
  label: string;
  modelKey: string;
  active: number;
  newPerWeek: number;
  gonePerWeek: number;
  medianPrice: number | null;
  valued: boolean;
  modelSamples: number | null;
  errPct: number | null;
  deals: number;
  typicalDealMargin: number | null;
  dealsPerWeek: number;
  weeklyPotentialEur: number | null;
};

export type CarHunt = {
  cells: CarHuntCell[];
  windowDays: number;
  minDealMarginEur: number;
  valuedVariants: number;
  totalVariants: number;
  generatedAt: string;
  note: string;
};

export type CarPriceModel = {
  variantKey: string;
  label: string;
  level: "generazione" | "modello" | null;
  n: number;
  errPct: number;
  yearRange: [number, number];
  kmRange: [number, number];
  kwRange: [number, number] | null;
  perYearPct: number | null;
  per10kKmPct: number | null;
  per10pctKwPct: number | null;
  coupePct: number | null;
  dieselPct: number | null;
  automaticPct: number | null;
};

export async function fetchCarModels(signal?: AbortSignal): Promise<{ models: CarPriceModel[]; count: number }> {
  const res = await fetch(`${API_BASE_URL}/api/car-models`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`GET /api/car-models failed (${res.status})`);
  return res.json();
}

export type CarValue = {
  variantKey: string;
  expected: number | null;
  low?: number;
  high?: number;
  errPct?: number;
  n?: number;
  level?: string;
  reason?: string;
  costs?: ApiOpportunity["acquisitionCosts"];
  maxBid?: number | null;
};

export async function fetchCarValue(
  q: { variant: string; year: number; km: number; kw?: number | null; diesel?: boolean;
       automatic?: boolean; coupe?: boolean },
  signal?: AbortSignal,
): Promise<CarValue> {
  const p = new URLSearchParams({ variant: q.variant, year: String(q.year), km: String(q.km) });
  if (q.kw) p.set("kw", String(q.kw));
  if (q.diesel) p.set("diesel", "true");
  if (q.automatic) p.set("automatic", "true");
  if (q.coupe) p.set("coupe", "true");
  const res = await fetch(`${API_BASE_URL}/api/car-value?${p.toString()}`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`GET /api/car-value failed (${res.status})`);
  return res.json();
}

export async function fetchCarHunt(signal?: AbortSignal): Promise<CarHunt> {
  const res = await fetch(`${API_BASE_URL}/api/car-hunt`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`GET /api/car-hunt failed (${res.status})`);
  return res.json();
}

export async function fetchRepairMatrix(signal?: AbortSignal): Promise<RepairMatrix> {
  const res = await fetch(`${API_BASE_URL}/api/repair-matrix`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`GET /api/repair-matrix failed (${res.status})`);
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
  conditionTier: string;
  days: number;
  price: number | null;
};

export type TimeToSaleData = {
  records: TimeToSaleRecord[];
  models: string[];
  colors: string[];
  storages: number[];
  conditions: string[];
  sampleSold: number;
  /** Auto: etichette delle due dimensioni (alimentazione, km). */
  dimLabels?: { color: string; storage: string } | null;
  storageUnit?: "gb" | "km";
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
  estimate?: DealEstimate;
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
      "stage" | "offer_price" | "buy_price" | "sell_price" | "extra_costs" | "notes" | "repair"
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
  /** Chiamate a Subito nel giro (migrazione 18). */
  requests?: number | null;
  /** Target non ricongiunti con la scansione precedente = annunci persi. */
  gaps?: number | null;
};

export type TargetCoverage = {
  query: string;
  active: number;
  sold: number;
  total: number;
  new24h: number;
};

export type Coverage = {
  activeTargets: number | null;
  activeListings: number | null;
  new24h: number;
  targets: TargetCoverage[];
};

export type Pacing = {
  gapS: number;
  minGapS: number;
  blockedForS: number;
  consecutiveBlocks: number;
  totalBlocks: number;
};

export type ScraperHealth = {
  proxy_configured: boolean;
  pacing?: Pacing;
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

export type DataQuality = {
  category: string;
  activeListings: number;
  coverage: {
    subitoTotal: number | null;
    seenLastInventory: number | null;
    keptLastInventory: number | null;
    inventoryAt: string | null;
    inventoryComplete: boolean | null;
    readLastInventory?: number | null;
    /** Annunci della ricerca letti / dichiarati da Subito. */
    seenPct: number | null;
  };
  /** Esito dell'ultimo inventario (anche interrotto o incompleto). */
  inventoryResult?: {
    at: string;
    aborted?: boolean;
    error?: string;
    complete?: boolean;
    candidates?: number;
    checked?: number;
    removed?: number;
    republished_merged?: number;
    capped?: number;
    short_bands?: string[];
  } | null;
  /** % di annunci attivi con il campo estratto. */
  fieldsPct: Record<string, number>;
  last24h: { runs: number; down: number; requests: number; gaps: number; new: number };
  removed7d: number;
  /** Ritardi: pubblicazione → scoperta (ultime 24h) e scoperta → alert (7 giorni). */
  latency?: {
    published24h: number | null;
    discoveryP50Min: number | null;
    discoveryP95Min: number | null;
    lateOver2h: number | null;
    alerts7d: number;
    alertP50Min: number | null;
    alertP95Min: number | null;
  };
  /** Auto: ciclo d'inventario a rotazione e generazioni valutabili. */
  autoCycle?: {
    slices: number | null; walked: string[]; nextSlice: number | null; cycleStart: string | null;
    subitoTotal: number | null; bands: number; valuedVariants?: number; totalVariants?: number;
  } | null;
  autoExcluded?: { altroModelloORicambio: number; generazioneIncerta: number } | null;
  /** Annunci con foto ancora da scaricare (backfill dalla CDN). */
  photoQueue?: number | null;
  /** Candidati venduti in coda di verifica (pagina per pagina, a pezzi). */
  verifyQueue?: number | null;
  /** Alert degli ultimi 7 giorni: consegnati, falliti (devono essere 0), mai
   *  inviati (Telegram non configurato: registrati solo per il ricontrollo). */
  alertDelivery7d?: { delivered: number; failed: number; not_sent: number } | null;
  /** Quanto resta online un affare dopo l'alert: quota sparita entro N minuti
   *  (solo affari più vecchi di N) ed emivita = primo orizzonte con metà sparita. */
  dealHalfLife?: {
    n: number; gone: number; withinPct: Record<string, number | null>; halfLifeMin: number | null;
  } | null;
  /** Deriva del formato: campi che si svuotano negli ultimi annunci rispetto alla base. */
  drift?: {
    at: string; recentN: number; baseN: number;
    alarms: Record<string, { recent: number; base: number; since: string }>;
  } | null;
  /** Richieste a Subito di oggi per lavoro (stesso IP: il budget conta). */
  requestsToday?: {
    jobs: Record<string, { requests: number; blocks: number }>; total: number; blocks: number;
  } | null;
  /** Esito del servizio `backup` (dump verificato + copia delle foto). */
  backup?: {
    state: "ok" | "fallito" | "vecchio" | "assente";
    at?: string | null;
    error?: string | null;
    sizeKb?: number | null;
    lastOkAgeHours?: number | null;
    restoredListings?: number | null;
    media?: { files: number; mirrored: number } | null;
    retentionDays?: number | null;
  };
};

export async function fetchDataQuality(
  category = "smartphone",
  signal?: AbortSignal,
): Promise<DataQuality> {
  const res = await fetch(`${API_BASE_URL}/health/data-quality?category=${category}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new Error(`GET /health/data-quality failed (${res.status})`);
  return res.json();
}

/** Obiettivi della Goal Version ("Come si sa che ci siamo") misurati ora. */
export type Goal = {
  key: string; label: string; target: string;
  value: string | number | null;
  /** true = raggiunto, false = no, null = non ancora misurabile. */
  ok: boolean | null;
  detail: string;
};
export type GoalsState = { at: string; goals: Goal[]; met: number; total: number };

export async function fetchGoals(signal?: AbortSignal): Promise<GoalsState> {
  const res = await fetch(`${API_BASE_URL}/health/goals`, { cache: "no-store", signal });
  if (!res.ok) throw new Error(`GET /health/goals failed (${res.status})`);
  return res.json();
}

/* ------------------------------------------------------------- Impostazioni */

export type AppSettings = {
  alert_min_margin_pct: number;
  alert_min_drop_pct: number;
  alert_min_score: number;
  alert_min_repair_margin_eur: number;
  target_margin_pct: Record<string, number>;
  apple_part_eur: Record<string, Record<string, number>>;
  repair_source: "aftermarket" | "apple";
  apple_return_credit: boolean;
  repair_labor_eur: Record<string, number>;
  // Auto: costi d'acquisto (passaggio di proprietà & co.)
  car_ipt_province_pct?: number;
  car_agency_eur?: number;
  car_prep_eur?: number;
  car_dealer?: boolean;
  car_hold_days?: number;
  car_insurance_month_eur?: number;
  car_parking_month_eur?: number;
  car_bollo_year_eur?: number;
  // Auto: criteri degli alert Telegram
  car_alert_min_net_margin_eur?: number;
  car_alert_max_price?: number;
  car_alert_brands?: string[];
  car_alert_zones?: string[];
  car_alert_radius_km?: number;
  /** Il margine deve superare N volte l'errore tipico del modello di prezzo (€). */
  car_alert_min_err_multiple?: number;
  home_town?: string;
  // Tempi per il profitto per ora (ipotesi da tarare con i tuoi dati)
  tv_speed_kmh?: number;
  tv_meet_min?: number;
  tv_sell_min?: number;
  tv_repair_min?: Record<string, number>;
  tv_unknown_distance_km?: number;
  tv_car_extra_min?: number;
  tv_arrange_min?: number;
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

/** Alert di prova alla chat salvata (verifica token, chat, foto e bottoni). */
export async function testTelegram(
  category: "smartphone" | "automobile" | "ops",
): Promise<{ ok: boolean; detail: string }> {
  const res = await fetch(`${API_BASE_URL}/api/settings/telegram-test?category=${category}`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/settings/telegram-test failed (${res.status})`);
  return res.json();
}

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
