import { ArrowDownRight, ArrowUpRight, TrendingUp } from "lucide-react";

import { MarketTrendChart } from "@/components/market-trend-chart";
import { getMarketTrends } from "@/lib/api";

export default async function Home() {
  const trendData = await getMarketTrends();
  const firstPrice = trendData[0]?.price ?? 0;
  const lastPrice = trendData.at(-1)?.price ?? 0;
  const variation = firstPrice
    ? Math.round(((lastPrice - firstPrice) / firstPrice) * 1000) / 10
    : 0;

  return (
    <section className="space-y-6">
      <div className="flex flex-col gap-2">
        <p className="text-sm font-medium uppercase tracking-[0.12em] text-teal-700">
          Market Overview
        </p>
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div>
            <h1 className="text-3xl font-semibold text-zinc-950">
              iPhone 13 Pro market
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
              Prezzi medi osservati negli ultimi 6 mesi per individuare trend,
              timing di acquisto e soglie di rivendita.
            </p>
          </div>
          <div className="flex h-10 items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-700">
            <TrendingUp className="h-4 w-4 text-teal-700" aria-hidden="true" />
            Last update mock
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <p className="text-sm text-zinc-500">Prezzo medio attuale</p>
          <p className="mt-2 text-2xl font-semibold text-zinc-950">
            €{lastPrice}
          </p>
        </div>
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <p className="text-sm text-zinc-500">Variazione 6 mesi</p>
          <div className="mt-2 flex items-center gap-2">
            {variation >= 0 ? (
              <ArrowUpRight className="h-5 w-5 text-emerald-600" />
            ) : (
              <ArrowDownRight className="h-5 w-5 text-red-600" />
            )}
            <p className="text-2xl font-semibold text-zinc-950">
              {variation > 0 ? "+" : ""}
              {variation}%
            </p>
          </div>
        </div>
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <p className="text-sm text-zinc-500">Buy zone stimata</p>
          <p className="mt-2 text-2xl font-semibold text-zinc-950">
            €430-€470
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-zinc-200 bg-white p-4 md:p-6">
        <div className="mb-5 flex flex-col justify-between gap-2 md:flex-row md:items-center">
          <div>
            <h2 className="text-lg font-semibold text-zinc-950">
              Andamento prezzo iPhone 13 Pro
            </h2>
            <p className="text-sm text-zinc-500">Media marketplace, EUR</p>
          </div>
          <span className="w-fit rounded-md bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800">
            Mock data
          </span>
        </div>
        <MarketTrendChart data={trendData} />
      </div>
    </section>
  );
}
