"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calculator, LineChart, Radar } from "lucide-react";

const navItems = [
  { href: "/", label: "Market Overview", icon: LineChart },
  { href: "/scanner", label: "Opportunity Scanner", icon: Radar },
  { href: "/calculator", label: "Margin Calculator", icon: Calculator },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="border-b border-zinc-200 bg-white md:min-h-screen md:w-72 md:border-b-0 md:border-r">
      <div className="flex h-full flex-col gap-6 p-4 md:p-5">
        <Link href="/" className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-950 text-sm font-semibold text-white">
            RS
          </div>
          <div>
            <p className="text-sm font-semibold text-zinc-950">ResellerOS</p>
            <p className="text-xs text-zinc-500">Auto & iPhone desk</p>
          </div>
        </Link>

        <nav className="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  "flex h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
                  active
                    ? "bg-teal-700 text-white"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-950",
                ].join(" ")}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
