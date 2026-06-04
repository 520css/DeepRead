"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Conversation } from "@/lib/schema";
import { fetchFromApi } from "@/lib/api";
import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

interface BranchDirectoryProps {
    paperId: string;
    activeConversationId: string | null;
    onSwitchConversation: (convId: string) => void;
}

export function BranchDirectory({
    paperId,
    activeConversationId,
    onSwitchConversation,
}: BranchDirectoryProps) {
    const [branches, setBranches] = useState<Conversation[]>([]);
    const [isOpen, setIsOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const panelRef = useRef<HTMLDivElement>(null);
    const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const fetchBranches = useCallback(async () => {
        if (!paperId) return;
        setLoading(true);
        try {
            const data = await fetchFromApi(`/api/conversation/paper/${paperId}/branches`);
            setBranches(data.branches || []);
        } catch {
            // silent
        } finally {
            setLoading(false);
        }
    }, [paperId]);

    useEffect(() => { fetchBranches(); }, [fetchBranches]);
    useEffect(() => { fetchBranches(); }, [activeConversationId, fetchBranches]);

    // Close on click outside
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: MouseEvent) => {
            if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, [isOpen]);

    // Don't render trigger if no branches at all
    if (!loading && branches.length === 0) return null;

    const handleMouseEnter = () => {
        if (closeTimer.current) clearTimeout(closeTimer.current);
        setIsOpen(true);
    };

    const handleMouseLeave = () => {
        closeTimer.current = setTimeout(() => setIsOpen(false), 300);
    };

    return (
        <div
            ref={panelRef}
            className="absolute right-3 bottom-28 z-40"
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            {/* Popover card */}
            {isOpen && (
                <div className={cn(
                    "absolute bottom-full right-0 mb-2 w-56",
                    "rounded-xl border border-border bg-background/97",
                    "shadow-xl shadow-black/10 dark:shadow-black/30",
                    "backdrop-blur-md animate-in fade-in slide-in-from-bottom-2 duration-200",
                )}>
                    {/* Header */}
                    <div className="flex items-center gap-1.5 px-3 py-2.5 border-b border-border/50">
                        <GitBranch className="size-3 text-muted-foreground" />
                        <span className="text-[11px] font-medium text-muted-foreground tracking-wide uppercase">
                            对话分支
                        </span>
                        {branches.length > 0 && (
                            <span className="text-[10px] bg-muted/60 text-muted-foreground px-1.5 py-0.5 rounded-full ml-auto">
                                {branches.length}
                            </span>
                        )}
                    </div>

                    {/* List */}
                    <div className="max-h-64 overflow-y-auto py-1">
                        {loading ? (
                            <div className="px-3 py-6 text-[11px] text-muted-foreground text-center">
                                加载中...
                            </div>
                        ) : (
                            branches.map((b) => {
                                const isActive = String(b.id) === String(activeConversationId);
                                return (
                                    <button
                                        key={b.id}
                                        onClick={() => {
                                            onSwitchConversation(b.id);
                                            setIsOpen(false);
                                        }}
                                        className={cn(
                                            "w-full text-left px-3 py-2 transition-colors",
                                            "hover:bg-muted/40",
                                            isActive && "bg-blue-50/80 dark:bg-blue-950/50 border-l-[3px] border-blue-500 pl-[9px]"
                                        )}
                                    >
                                        <div className={cn(
                                            "text-[12px] font-medium truncate",
                                            isActive
                                                ? "text-blue-700 dark:text-blue-300"
                                                : "text-foreground/80"
                                        )}>
                                            {b.branchReason || b.title || "未命名"}
                                        </div>
                                        {b.branchReason && (
                                            <div className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">
                                                {b.branchReason}
                                            </div>
                                        )}
                                    </button>
                                );
                            })
                        )}
                    </div>
                </div>
            )}

            {/* Trigger button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1.5 rounded-full",
                    "text-[11px] text-muted-foreground/60",
                    "bg-background/60 backdrop-blur-sm border border-border/40",
                    "shadow-sm hover:shadow-md hover:text-muted-foreground hover:border-border",
                    "transition-all duration-200",
                    isOpen && "text-muted-foreground border-border shadow-md"
                )}
                title="对话分支"
            >
                <GitBranch className="size-3" />
                <span className="tabular-nums">{branches.length}</span>
            </button>
        </div>
    );
}
