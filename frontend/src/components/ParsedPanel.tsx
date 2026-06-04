"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchFromApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Loader2, Sparkles, FileText, CheckCircle2, Clock, AlertCircle } from "lucide-react";
import { AnimatedMarkdown } from "@/components/AnimatedMarkdown";

type Mode = "speedread" | "fullparse";
type ParseStatus = "none" | "quick" | "verified" | "failed";

interface ParsedPanelProps {
    paperId: string;
    paperTitle?: string;
}

export function ParsedPanel({ paperId, paperTitle: _title }: ParsedPanelProps) {
    const [mode, setMode] = useState<Mode>("speedread");
    const [summary, setSummary] = useState<string | null>(null);
    const [fullText, setFullText] = useState<string | null>(null);
    const [parseStatus, setParseStatus] = useState<ParseStatus>("none");
    const [totalChars, setTotalChars] = useState(0);
    const [generating, setGenerating] = useState(false);
    const [loading, setLoading] = useState(true);

    // ─── Load everything on mount ───
    useEffect(() => {
        let timer: ReturnType<typeof setInterval>;
        (async () => {
            setLoading(true);

            try {
                // Get real parse_status from dedicated endpoint (raw DB value, not mapped)
                const s = await fetchFromApi(`/api/paper/${paperId}/status`);
                const status: ParseStatus = s.parse_status || "none";
                setParseStatus(status);

                // Load summary from paper detail
                try {
                    const p = await fetchFromApi(`/api/paper?id=${paperId}`);
                    if (p.summary && p.summary !== "None") {
                        setSummary(p.summary);
                    }
                } catch {}

                // If already verified, load full text immediately (no polling needed)
                if (status === "verified") {
                    try {
                        const d = await fetchFromApi(`/api/paper/${paperId}/parsed`);
                        if (d.full_text) {
                            setFullText(d.full_text);
                            setTotalChars(d.total_chars || 0);
                        }
                    } catch {}
                }

                // Only poll if still processing (quick/pending)
                if (status !== "verified" && status !== "failed") {
                    timer = setInterval(async () => {
                        try {
                            const s2 = await fetchFromApi(`/api/paper/${paperId}/status`);
                            const s3: ParseStatus = s2.parse_status || "none";
                            setParseStatus(s3);
                            if (s3 === "verified") {
                                clearInterval(timer);
                                const d = await fetchFromApi(`/api/paper/${paperId}/parsed`);
                                if (d.full_text) {
                                    setFullText(d.full_text);
                                    setTotalChars(d.total_chars || 0);
                                }
                            } else if (s3 === "failed") {
                                clearInterval(timer);
                            }
                        } catch {}
                    }, 30000);
                }
            } catch {}

            setLoading(false);
        })();
        return () => { if (timer) clearInterval(timer); };
    }, [paperId]);

    // ─── Generate Speed Read ───
    const generateSpeedRead = useCallback(async () => {
        setGenerating(true);
        try {
            const res = await fetchFromApi(`/api/paper/${paperId}/summary`, { method: "POST" });
            const content = res.summary || res.raw || "";
            setSummary(content);
            setMode("speedread");
        } catch (e) {
            console.error("Generate summary failed:", e);
        } finally {
            setGenerating(false);
        }
    }, [paperId]);

    const statusBadge = () => {
        switch (parseStatus) {
            case "verified": return <Badge variant="default" className="bg-green-500 gap-1"><CheckCircle2 size={10} />Completed</Badge>;
            case "quick": return <Badge variant="secondary" className="gap-1"><Clock size={10} className="animate-spin" />Parsing...</Badge>;
            case "failed": return <Badge variant="destructive" className="gap-1"><AlertCircle size={10} />Failed</Badge>;
            default: return <Badge variant="outline" className="gap-1"><Clock size={10} />Pending</Badge>;
        }
    };

    const content = mode === "speedread" ? summary : fullText;

    return (
        <div className="flex flex-col h-full min-h-0">
            {/* Header — fixed */}
            <div className="flex items-center gap-2 p-2 border-b shrink-0">
                <div className="flex bg-muted rounded-lg p-0.5 gap-0.5">
                    <Button
                        size="sm"
                        variant={mode === "speedread" ? "default" : "ghost"}
                        className="h-7 text-xs"
                        onClick={() => setMode("speedread")}
                    >
                        <Sparkles size={12} className="mr-1" />Speed Read
                    </Button>
                    <Button
                        size="sm"
                        variant={mode === "fullparse" ? "default" : "ghost"}
                        className="h-7 text-xs"
                        onClick={() => setMode("fullparse")}
                        disabled={!fullText}
                    >
                        <FileText size={12} className="mr-1" />Full Parse
                    </Button>
                </div>
                <div className="flex-1" />
                {statusBadge()}
            </div>

            {/* Body — scrollable */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
                {loading ? (
                    <div className="flex justify-center py-12"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
                ) : content ? (
                    <AnimatedMarkdown content={content} />
                ) : mode === "speedread" ? (
                    <Card className="p-8 text-center space-y-4 bg-gradient-to-b from-blue-50/50 dark:from-blue-950/20">
                        <Sparkles size={32} className="mx-auto text-blue-400" />
                        <div>
                            <p className="font-medium">AI Speed Read</p>
                            <p className="text-sm text-muted-foreground mt-1">
                                Generate a quick summary of this paper in seconds
                            </p>
                        </div>
                        <Button onClick={generateSpeedRead} disabled={generating}>
                            {generating ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Sparkles size={14} className="mr-1" />}
                            Generate Speed Read
                        </Button>
                    </Card>
                ) : (
                    <Card className="p-8 text-center space-y-4 bg-gradient-to-b from-amber-50/50 dark:from-amber-950/20">
                        <Clock size={32} className="mx-auto text-amber-400 animate-pulse" />
                        <div>
                            <p className="font-medium">Deep Parse In Progress</p>
                            <p className="text-sm text-muted-foreground mt-1">
                                Marker is analyzing the PDF. This may take 10–20 minutes.
                            </p>
                        </div>
                    </Card>
                )}
            </div>

            {/* Footer — fixed */}
            {totalChars > 0 && mode === "fullparse" && (
                <div className="p-2 border-t text-[10px] text-muted-foreground text-center shrink-0">
                    {totalChars.toLocaleString()} chars
                </div>
            )}
            {summary && mode === "speedread" && (
                <div className="p-2 border-t text-[10px] text-muted-foreground text-center shrink-0">
                    AI-generated &bull; <span className="cursor-pointer text-blue-400 hover:underline" onClick={generateSpeedRead}>Regenerate</span>
                </div>
            )}
        </div>
    );
}
