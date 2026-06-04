"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { GripHorizontal, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AnimatedMarkdown } from "@/components/AnimatedMarkdown";

interface TranslationPopoverProps {
    text: string | null;
    isLoading: boolean;
    position: { x: number; y: number } | null;
    onClose: () => void;
}

export function TranslationPopover({ text, isLoading, position, onClose }: TranslationPopoverProps) {
    const ref = useRef<HTMLDivElement>(null);
    const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
    const dragging = useRef(false);
    const dragOffset = useRef({ x: 0, y: 0 });

    // Sync internal position with prop
    useEffect(() => {
        setPos(position);
    }, [position]);

    // Dragging
    const onDragStart = useCallback((e: React.MouseEvent) => {
        dragging.current = true;
        const rect = ref.current?.getBoundingClientRect();
        if (rect) {
            dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
        }
        e.preventDefault();
    }, []);

    useEffect(() => {
        const onMove = (e: MouseEvent) => {
            if (!dragging.current) return;
            setPos({
                x: Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - 380)),
                y: Math.max(0, e.clientY - dragOffset.current.y),
            });
        };
        const onUp = () => { dragging.current = false; };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        return () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };
    }, []);

    // Close on outside click
    useEffect(() => {
        if (!pos) return;
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as HTMLElement)) {
                onClose();
            }
        };
        const timer = setTimeout(() => document.addEventListener("mousedown", handler), 100);
        return () => {
            clearTimeout(timer);
            document.removeEventListener("mousedown", handler);
        };
    }, [pos, onClose]);

    // Close on Escape
    useEffect(() => {
        if (!pos) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        document.addEventListener("keydown", handler);
        return () => document.removeEventListener("keydown", handler);
    }, [pos, onClose]);

    if (!pos) return null;

    const left = Math.min(pos.x, window.innerWidth - 396);

    return (
        <div
            ref={ref}
            className="fixed z-40 bg-background border border-border rounded-lg shadow-xl max-w-[380px] min-w-[260px] max-h-[70vh] flex flex-col"
            style={{ left: `${Math.max(8, left)}px`, top: `${Math.max(8, pos.y)}px` }}
        >
            {/* Drag handle + title bar */}
            <div
                className="flex items-center justify-between p-2 pl-3 cursor-grab active:cursor-grabbing border-b border-border select-none shrink-0"
                onMouseDown={onDragStart}
            >
                <div className="flex items-center gap-2">
                    <GripHorizontal size={12} className="text-muted-foreground" />
                    <span className="text-[11px] font-medium text-muted-foreground">
                        {isLoading ? "Translating..." : "Translation"}
                    </span>
                </div>
                <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => { e.stopPropagation(); onClose(); }}
                >
                    <X size={14} />
                </Button>
            </div>

            {/* Content */}
            <div className="p-3 overflow-y-auto flex-1">
                {isLoading ? (
                    <div className="flex items-center gap-2 py-4 text-xs text-muted-foreground">
                        <Loader2 size={14} className="animate-spin" />
                        Translating with DeepSeek...
                    </div>
                ) : text ? (
                    <div className="text-xs [&_p]:text-xs [&_*]:!text-xs [&_h1]:!text-sm [&_h2]:!text-sm [&_h3]:!text-xs prose dark:prose-invert max-w-none leading-snug">
                        <AnimatedMarkdown content={text} />
                    </div>
                ) : (
                    <p className="text-xs text-muted-foreground py-2">
                        {text === null ? "" : "Translation failed. Please try again."}
                    </p>
                )}
            </div>
        </div>
    );
}
