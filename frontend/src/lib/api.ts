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
