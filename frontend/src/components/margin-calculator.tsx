"use client";

import { useMemo, useState } from "react";
import { Calculator } from "lucide-react";

type NumberInputProps = {
  label: string;
  value: number;
  suffix?: string;
  onChange: (value: number) => void;
};

function NumberInput({ label, value, suffix, onChange }: NumberInputProps) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-zinc-700">{label}</span>
      <div className="mt-2 flex h-11 items-center rounded-md border border-zinc-200 bg-white px-3 focus-within:border-teal-700 focus-within:ring-2 focus-within:ring-teal-700/15">
        <input
          type="number"
          min="0"
          step="0.01"
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="h-full w-full bg-transparent text-sm text-zinc-950 outline-none"
        />
        {suffix ? <span className="text-sm text-zinc-500">{suffix}</span> : null}
      </div>
    </label>
  );
}

export function MarginCalculator() {
  const [purchasePrice, setPurchasePrice] = useState(420);
  const [resalePrice, setResalePrice] = useState(560);
  const [platformFee, setPlatformFee] = useState(6.5);
  const [restorationCost, setRestorationCost] = useState(35);

  const result = useMemo(() => {
    const fees = resalePrice * (platformFee / 100);
    const netProfit = resalePrice - purchasePrice - fees - restorationCost;
    const marginPercent = resalePrice ? (netProfit / resalePrice) * 100 : 0;

    return {
      fees,
      netProfit,
      marginPercent,
    };
  }, [platformFee, purchasePrice, resalePrice, restorationCost]);

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <form className="grid gap-4 rounded-lg border border-zinc-200 bg-white p-5 md:grid-cols-2">
        <NumberInput
          label="Prezzo di acquisto"
          value={purchasePrice}
          suffix="EUR"
          onChange={setPurchasePrice}
        />
        <NumberInput
          label="Prezzo di rivendita"
          value={resalePrice}
          suffix="EUR"
          onChange={setResalePrice}
        />
        <NumberInput
          label="Fee piattaforma"
          value={platformFee}
          suffix="%"
          onChange={setPlatformFee}
        />
        <NumberInput
          label="Costi di ripristino"
          value={restorationCost}
          suffix="EUR"
          onChange={setRestorationCost}
        />
      </form>

      <div className="rounded-lg border border-zinc-200 bg-zinc-950 p-5 text-white">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-teal-500/20">
            <Calculator className="h-5 w-5 text-teal-200" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm text-zinc-300">Profitto netto stimato</p>
            <p className="text-3xl font-semibold">
              €{result.netProfit.toFixed(2)}
            </p>
          </div>
        </div>

        <dl className="mt-6 space-y-3 text-sm">
          <div className="flex justify-between border-t border-white/10 pt-3">
            <dt className="text-zinc-300">Commissioni</dt>
            <dd className="font-medium">€{result.fees.toFixed(2)}</dd>
          </div>
          <div className="flex justify-between border-t border-white/10 pt-3">
            <dt className="text-zinc-300">Margine netto</dt>
            <dd className="font-medium">{result.marginPercent.toFixed(1)}%</dd>
          </div>
          <div className="flex justify-between border-t border-white/10 pt-3">
            <dt className="text-zinc-300">Costo totale</dt>
            <dd className="font-medium">
              €{(purchasePrice + restorationCost + result.fees).toFixed(2)}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
