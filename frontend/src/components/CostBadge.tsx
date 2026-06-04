"use client";

import { useEffect, useState } from "react";
import { fetchFromApi } from "@/lib/api";
import { cn } from "@/lib/utils";

export function CostBadge() {
    const [cost, setCost] = useState<number | null>(null);
    const [limit, setLimit] = useState(20);
    const [pct, setPct] = useState(0);
    const [warning, setWarning] = useState(false);

    useEffect(() => {
        fetchFromApi("/api/stats/budget")
            .then((d) => {
                setCost(d.current_usd);
                setLimit(d.limit_usd);
                setPct(d.usage_pct);
                setWarning(d.warning);
            })
            .catch(() => {});
    }, []);

    if (cost === null) return null;

    return (
        <div
            className={cn(
                "flex items-center gap-1 text-[11px] h-7 px-2 rounded-md border font-medium transition-colors",
                warning
                    ? "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-400"
                    : "border-border bg-muted/40 text-muted-foreground hover:bg-muted/60"
            )}
            title={`${cost.toFixed(2)} / ${limit.toFixed(0)} USD used this month (${pct}%)`}
        >
            <svg className="size-3 opacity-60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8"/><path d="M12 18V6"/></svg>
            <span>${cost.toFixed(2)}</span>
            <span className="opacity-40">/ ${limit.toFixed(0)}</span>
            {warning && (
                <span className="tabular-nums ml-0.5">{pct}%</span>
            )}
        </div>
    );
}
