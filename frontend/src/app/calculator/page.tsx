import { MarginCalculator } from "@/components/margin-calculator";

export default function CalculatorPage() {
  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-[0.12em] text-teal-700">
          Margin Calculator
        </p>
        <h1 className="mt-2 text-3xl font-semibold text-zinc-950">
          Calcolo profitto netto
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">
          Stima rapida del margine dopo commissioni, ripristino e prezzo di
          rivendita atteso.
        </p>
      </div>

      <MarginCalculator />
    </section>
  );
}
