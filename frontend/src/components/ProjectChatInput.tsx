"use client";

import { useState, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Loader2, Send, ChevronDown, ChevronRight, Wrench } from "lucide-react";

const END_OF_STREAM = "END_OF_STREAM";
const API_BASE = "http://localhost:8000";

interface TraceStep {
    step: number;
    tool: string;
    params: Record<string, unknown>;
    observation?: string;
}

interface ChatMessage {
    role: "user" | "assistant";
    content: string;
    trace: TraceStep[];
    collapsed: boolean;
}

export default function ProjectChatInput({ projectId }: { projectId: number }) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const abortRef = useRef<AbortController | null>(null);

    const handleSend = async () => {
        if (!input.trim() || loading) return;
        const q = input.trim();
        setInput("");
        setLoading(true);

        const userMsg: ChatMessage = { role: "user", content: q, trace: [], collapsed: true };
        const aiMsg: ChatMessage = { role: "assistant", content: "", trace: [], collapsed: false };
        setMessages(prev => [...prev, userMsg, aiMsg]);

        const controller = new AbortController();
        abortRef.current = controller;

        try {
            const resp = await fetch(`${API_BASE}/api/projects/${projectId}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: q }),
                signal: controller.signal,
            });
            const text = await resp.text();
            let fullContent = "";
            let trace: TraceStep[] = [];
            let stepCount = 0;
            let pendingTool: { tool: string; params: Record<string, unknown> } | null = null;

            for (const raw of text.split(END_OF_STREAM)) {
                const chunk = raw.trim();
                if (!chunk) continue;
                try {
                    const ev = JSON.parse(chunk);
                    if (ev.type === "tool_call") {
                        stepCount++;
                        pendingTool = { tool: ev.content.tool || "?", params: ev.content.params || {} };
                    } else if (ev.type === "observation" && pendingTool) {
                        pendingTool.observation = typeof ev.content === "string" ? ev.content : "";
                        trace.push({ step: stepCount, tool: pendingTool, params: pendingTool.params, observation: pendingTool.observation });
                        pendingTool = null;
                    } else if (ev.type === "content") {
                        fullContent += typeof ev.content === "string" ? ev.content : "";
                    }
                    setMessages(prev => {
                        const u = [...prev];
                        const last = u.length - 1;
                        if (last >= 0 && u[last].role === "assistant") {
                            u[last] = { ...u[last], content: fullContent, trace: [...trace] };
                        }
                        return u;
                    });
                } catch { }
            }
        } catch (err) {
            if (err instanceof Error && err.name !== "AbortError") {
                setMessages(prev => {
                    const u = [...prev];
                    const last = u.length - 1;
                    if (last >= 0) u[last] = { ...u[last], content: "Error: " + (err instanceof Error ? err.message : "Unknown") };
                    return u;
                });
            }
        } finally {
            setLoading(false);
            abortRef.current = null;
        }
    };

    const handleStop = () => { abortRef.current?.abort(); setLoading(false); };

    return (
        <div className="mt-4 space-y-3 w-full">
            {messages.map((msg, i) => (
                <div key={i}>
                    {msg.role === "user" ? (
                        <div className="flex justify-end">
                            <div className="bg-primary/10 rounded-lg px-3 py-1.5 text-sm max-w-[80%]">{msg.content}</div>
                        </div>
                    ) : (
                        <div className="space-y-1">
                            {msg.trace.length > 0 && (
                                <button onClick={() => {
                                    setMessages(prev => prev.map((m, j) => j === i ? { ...m, collapsed: !m.collapsed } : m));
                                }} className="flex items-center gap-1 text-xs text-blue-600">
                                    {msg.collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                                    <Wrench className="w-3 h-3" />{msg.trace.length} steps
                                </button>
                            )}
                            {!msg.collapsed && msg.trace.map((s, j) => (
                                <div key={j} className="text-xs text-muted-foreground pl-4">
                                    [{s.step}] {s.tool}
                                </div>
                            ))}
                            {msg.content && <div className="text-sm whitespace-pre-wrap">{msg.content}</div>}
                        </div>
                    )}
                </div>
            ))}
            <div className="flex gap-2">
                <Textarea
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    placeholder="Ask about these papers..."
                    className="min-h-[40px] resize-none text-sm"
                    rows={1}
                />
                {loading ? (
                    <Button variant="destructive" size="sm" onClick={handleStop}><Loader2 className="w-4 h-4 animate-spin" /></Button>
                ) : (
                    <Button size="sm" onClick={handleSend} disabled={!input.trim()}><Send className="w-4 h-4" /></Button>
                )}
            </div>
        </div>
    );
}
