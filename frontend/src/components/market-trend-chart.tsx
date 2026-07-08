"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { MarketTrendPoint } from "@/lib/api";

type Props = {
  data: MarketTrendPoint[];
};

export function MarketTrendChart({ data }: Props) {
  return (
    <div className="h-[360px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 18, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e4e4e7" strokeDasharray="4 4" vertical={false} />
          <XAxis
            dataKey="month"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 12 }}
            dy={10}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#71717a", fontSize: 12 }}
            tickFormatter={(value) => `€${value}`}
            width={56}
          />
          <Tooltip
            cursor={{ stroke: "#0f766e", strokeWidth: 1 }}
            contentStyle={{
              border: "1px solid #e4e4e7",
              borderRadius: 8,
              boxShadow: "0 8px 24px rgba(24, 24, 27, 0.08)",
            }}
            formatter={(value) => [`€${value}`, "Prezzo medio"]}
            labelStyle={{ color: "#18181b", fontWeight: 600 }}
          />
          <Line
            type="monotone"
            dataKey="price"
            stroke="#0f766e"
            strokeWidth={3}
            dot={{ r: 4, strokeWidth: 2, fill: "#ffffff" }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
