import { ExternalLink, Radar } from "lucide-react";

import { getLiveOpportunities } from "@/lib/api";

export default async function ScannerPage() {
  const opportunities = await getLiveOpportunities();

  return (
    <section className="space-y-6">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.12em] text-teal-700">
            Opportunity Scanner
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-zinc-950">
            Live Opportunities
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
            Occasioni mockate ordinate per margine stimato e velocita di
            rotazione sul mercato.
          </p>
        </div>
        <div className="flex h-10 items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-700">
          <Radar className="h-4 w-4 text-teal-700" aria-hidden="true" />
          Live mock feed
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-100 text-xs uppercase tracking-[0.08em] text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-semibold">Modello</th>
                <th className="px-4 py-3 font-semibold">Prezzo trovato</th>
                <th className="px-4 py-3 font-semibold">Prezzo medio</th>
                <th className="px-4 py-3 font-semibold">Margine</th>
                <th className="px-4 py-3 font-semibold">Mercato</th>
                <th className="px-4 py-3 text-right font-semibold">Annuncio</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {opportunities.map((item) => (
                <tr key={item.id} className="hover:bg-zinc-50">
                  <td className="px-4 py-4">
                    <div className="font-medium text-zinc-950">{item.model}</div>
                    <div className="text-xs text-zinc-500">{item.source}</div>
                  </td>
                  <td className="px-4 py-4 font-semibold text-zinc-950">
                    €{item.foundPrice}
                  </td>
                  <td className="px-4 py-4 text-zinc-700">
                    €{item.averagePrice}
                  </td>
                  <td className="px-4 py-4">
                    <span className="rounded-md bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                      {item.marginPercent}%
                    </span>
                  </td>
                  <td className="px-4 py-4 text-zinc-700">{item.market}</td>
                  <td className="px-4 py-4 text-right">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-zinc-950 px-3 text-xs font-medium text-white hover:bg-zinc-800"
                    >
                      <ExternalLink className="h-4 w-4" aria-hidden="true" />
                      Vai all&apos;annuncio
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
