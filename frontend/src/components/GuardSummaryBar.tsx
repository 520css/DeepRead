"use client";

import { Shield, ShieldAlert, ThumbsUp, ThumbsDown, Loader2 } from "lucide-react";
import { fetchFromApi } from "@/lib/api";
import { useState } from "react";
import type { GuardInfo } from "@/components/utils/parseGuardResult";

export function FeedbackButtons({ messageId, className = "" }: { messageId?: string; className?: string }) {
    const [feedback, setFeedback] = useState<"up" | "down" | null>(null);
    const [showInput, setShowInput] = useState(false);
    const [desc, setDesc] = useState("");
    const [submitting, setSubmitting] = useState(false);

    const submit = async (isHallucination: boolean, d?: string) => {
        if (!messageId || submitting) return;
        setSubmitting(true);
        try {
            await fetchFromApi(`/api/message/${messageId}/feedback`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_hallucination: isHallucination, description: d || "" }),
            });
            setFeedback(isHallucination ? "down" : "up");
            setShowInput(false);
        } catch { /* ignore */ }
        finally { setSubmitting(false); }
    };

    if (!messageId || feedback) return <>{feedback === "up" ? <ThumbsUp size={11} className="text-emerald-500 shrink-0" /> : feedback === "down" ? <ThumbsDown size={11} className="text-red-500 shrink-0" /> : null}</>;

    return (
        <div className={`flex items-center gap-0.5 relative ${className}`}>
            <button className="inline-flex items-center justify-center w-5 h-5 rounded hover:bg-emerald-100 dark:hover:bg-emerald-900/30 text-muted-foreground hover:text-emerald-600 transition-colors" title="Accurate" onClick={() => submit(false)} disabled={submitting}><ThumbsUp size={11} /></button>
            <button className="inline-flex items-center justify-center w-5 h-5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-muted-foreground hover:text-red-500 transition-colors" title="Hallucination" onClick={() => setShowInput(true)} disabled={submitting}><ThumbsDown size={11} /></button>
            {showInput && (
                <div className="absolute bottom-6 right-0 bg-background border border-border rounded-md shadow-lg p-1.5 z-20 w-48 max-w-[calc(100vw-2rem)]">
                    <textarea className="w-full text-[11px] border border-border rounded p-1 resize-none focus:outline-none min-h-[36px]" placeholder="What's wrong?" value={desc} onChange={e => setDesc(e.target.value)} rows={2} autoFocus />
                    <div className="flex gap-1 mt-1 justify-end">
                        <button className="text-[10px] px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80" onClick={() => setShowInput(false)}>Cancel</button>
                        <button className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400" onClick={() => submit(true, desc)} disabled={submitting}>{submitting ? <Loader2 size={10} className="animate-spin" /> : "Report"}</button>
                    </div>
                </div>
            )}
        </div>
    );
}

interface GuardSummaryBarProps {
    guardInfo: GuardInfo | null;
    className?: string;
}

export function GuardSummaryBar({ guardInfo, className = "" }: GuardSummaryBarProps) {
    if (!guardInfo) return null;

    const { similarity, similarityPassed, suspiciousNumbers, failedPages, hasIssues } = guardInfo;

    return (
        <div className={`flex items-center gap-2 mt-1.5 text-[11px] ${className}`}>
            {/* Trust summary */}
            <div className="flex items-center gap-1.5 text-muted-foreground">
                {hasIssues ? (
                    <ShieldAlert size={12} className="text-amber-500 shrink-0" />
                ) : (
                    <Shield size={12} className="text-emerald-500 shrink-0" />
                )}
                {similarity !== null && (
                    <span className={similarityPassed ? "" : "text-amber-500 font-medium"}>
                        sim {Math.round(similarity * 100)}%
                    </span>
                )}
                {failedPages.size > 0 && (
                    <span className="text-amber-500">
                        · cite {failedPages.size} ⚠
                    </span>
                )}
                {suspiciousNumbers.length > 0 && (
                    <span className="text-amber-500">
                        · num {suspiciousNumbers.length} ⚠
                    </span>
                )}
                {!hasIssues && similarity !== null && (
                    <span className="text-emerald-500">verified</span>
                )}
            </div>

        </div>
    );
}
