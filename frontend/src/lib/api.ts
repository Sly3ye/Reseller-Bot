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

export type ScorePoint = { label: string; points: number };

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
  description: string | null;
  images: string[];
  foundAt: string | null;
  daysOnline: number | null;
  source: string | null;
  status: string | null;
  url: string;
  // Segnale NLP + venditore
  sellerType: string | null;
  sellerActiveCount: number | null;
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
  // Deal Score + assistente trattativa
  score: number;
  scoreBreakdown: ScorePoint[];
  repair: RepairInfo | null;
  defectPenaltyEur: number | null;
  suggestedOffer: number | null;
};

export type ApiModelStat = {
  name: string;
  avg: number | null;
  sample: number | null;
  changePct: number | null;
  avgDaysToSell: number | null;
  sampleSold: number | null;
  fastSalePrice: number | null;
  maxSalePrice: number | null;
  series: { date: string; price: number }[];
};

export type ApiTrends = {
  activeListings: number;
  avgMarketPrice: number | null;
  outliersFiltered: number | null;
  avgDaysToSell: number | null;
  trend: { date: string; price: number }[];
  trendProduct: string | null;
  models: ApiModelStat[];
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
};

export type DealsSummary = {
  totalDeals: number;
  sold: number;
  openDeals: number;
  investedOpen: number;
  realizedProfit: number;
  avgRealMarginPct: number | null;
};

export async function fetchOpportunities(
  category: Category,
  signal?: AbortSignal,
): Promise<ApiOpportunity[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/opportunities?category=${category}`,
    { cache: "no-store", signal },
  );
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
