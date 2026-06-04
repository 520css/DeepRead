"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Loader2, ChevronDown, ChevronRight, Wrench, FileText, Eye, Zap, Copy, Check, Pencil, ChevronLeft } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { BranchDirectory } from "@/components/BranchDirectory";

const END_OF_STREAM = "END_OF_STREAM";
const API_BASE = "http://localhost:8000";

interface ToolCall {
  tool: string;
  params: Record<string, unknown>;
  observation?: string;
}

interface TraceStep {
  step: number;
  tool: ToolCall;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  trace: TraceStep[];
  collapsed: boolean;
}

function parseSSEChunk(chunk: string) {
  try {
    return JSON.parse(chunk);
  } catch {
    return null;
  }
}

export default function AgentPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<number>(0);
  const [conversationParentId, setConversationParentId] = useState<string | null>(null);
  const [branchPointIndex, setBranchPointIndex] = useState<number>(0);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [isBranching, setIsBranching] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load history when URL param changes
  useEffect(() => {
    const cid = searchParams.get("conv_id");
    const id = cid ? parseInt(cid, 10) : 0;
    if (id > 0) {
      setConversationId(id);
      setMessages([]);
      loadHistory(id);
    } else {
      setConversationId(0);
      setMessages([]);
    }
  }, [searchParams]);

  const loadHistory = async (convId: number) => {
    setLoadingHistory(true);
    try {
      const resp = await fetch(`${API_BASE}/api/conversation/${convId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      const msgs: Message[] = [];
      for (const m of data.messages || []) {
        msgs.push({
          role: m.role as "user" | "assistant",
          content: m.content || "",
          trace: [],
          collapsed: false,
        });
      }
      setMessages(msgs);
      // Capture tree metadata
      if (data.conversation?.parentId) setConversationParentId(data.conversation.parentId);
      else setConversationParentId(null);
      if (data.conversation?.branchPointIndex != null) setBranchPointIndex(data.conversation.branchPointIndex);
      else setBranchPointIndex(0);
    } catch (e) {
      console.error("Failed to load agent history:", e);
    } finally {
      setLoadingHistory(false);
    }
  };

  const switchConversation = (convId: string) => {
    router.push(`/agent?conv_id=${convId}`);
  };

  const handleEditSubmit = async (msgIndex: number) => {
    if (!editText.trim() || !conversationId || isBranching) return;
    setIsBranching(true);
    const editedContent = editText.trim();
    try {
      // 1. Create branch
      const branchResp = await fetch(`${API_BASE}/api/conversation/${conversationId}/branch-at`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ edit_message_index: msgIndex, branch_reason: editedContent.slice(0, 30) }),
      });
      const branchData = await branchResp.json();
      const newConvId = branchData.id;
      if (!newConvId) throw new Error("Branch failed");

      // 2. Switch to new conversation
      setConversationId(parseInt(newConvId));
      setEditingIdx(null);
      setEditText("");

      // 3. Add user message
      const userMsg: Message = { role: "user", content: editedContent, trace: [], collapsed: false };
      setMessages(prev => [...prev, userMsg]);

      // 4. Stream AI response
      setStreaming(true);
      setStatusText("Thinking...");
      const assistantMsg: Message = { role: "assistant", content: "", trace: [], collapsed: false };
      setMessages(prev => [...prev, assistantMsg]);

      const controller = new AbortController();
      abortRef.current = controller;

      const response = await fetch(`${API_BASE}/api/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: editedContent, conversation_id: parseInt(newConvId) }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      let fullContent = "";
      const currentTrace: TraceStep[] = [];

      for (const rawChunk of text.split(END_OF_STREAM)) {
        const chunk = rawChunk.trim();
        if (!chunk) continue;
        const evt = parseSSEChunk(chunk);
        if (!evt) continue;
        if (evt.type === "content") fullContent += typeof evt.content === "string" ? evt.content : "";

        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = { ...updated[lastIdx], content: fullContent, trace: [...currentTrace] };
          }
          return updated;
        });
      }

      // Update URL with new conv_id
      router.replace(`/agent?conv_id=${newConvId}`, { scroll: false });

      // Reload from DB to get complete clean state
      setMessages([]);
      loadHistory(parseInt(newConvId));
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      console.error("Edit branch error:", err);
    } finally {
      setStreaming(false);
      setStatusText("");
      setIsBranching(false);
      abortRef.current = null;
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const toggleCollapse = (msgIdx: number) => {
    setMessages((prev) =>
      prev.map((m, i) => (i === msgIdx ? { ...m, collapsed: !m.collapsed } : m))
    );
  };

  const handleSend = useCallback(async () => {
    if (!input.trim() || streaming) return;

    const question = input.trim();
    setInput("");
    setStreaming(true);
    setStatusText("Thinking...");

    const userMsg: Message = { role: "user", content: question, trace: [], collapsed: false };
    const assistantMsg: Message = { role: "assistant", content: "", trace: [], collapsed: false };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE}/api/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const text = await response.text();
      let fullContent = "";
      let currentTrace: TraceStep[] = [];
      let stepCount = 0;
      let pendingTool: ToolCall | null = null;

      for (const rawChunk of text.split(END_OF_STREAM)) {
        const chunk = rawChunk.trim();
        if (!chunk) continue;

        const evt = parseSSEChunk(chunk);
        if (!evt) continue;

        const type = evt.type;
        const content = evt.content;

        if (type === "status") {
          setStatusText(typeof content === "string" ? content : JSON.stringify(content));
        } else if (type === "tool_call") {
          stepCount++;
          pendingTool = { tool: content.tool || "?", params: content.params || {} };
        } else if (type === "observation") {
          if (pendingTool) {
            pendingTool.observation = typeof content === "string" ? content : JSON.stringify(content);
            currentTrace.push({ step: stepCount, tool: { ...pendingTool } });
            pendingTool = null;
          }
        } else if (type === "content") {
          fullContent += typeof content === "string" ? content : "";
        } else if (type === "done") {
          setStatusText("");
          if (content?.conv_id && !conversationId) {
            const cid = content.conv_id;
            setConversationId(cid);
            router.replace(`/agent?conv_id=${cid}`, { scroll: false });
          }
        }

        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: fullContent,
              trace: [...currentTrace],
            };
          }
          return updated;
        });
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setStatusText(`Error: ${err instanceof Error ? err.message : "Unknown"}`);
    } finally {
      setStreaming(false);
      setStatusText("");
      abortRef.current = null;
    }
  }, [input, streaming, conversationId, router]);

  const handleStop = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setStatusText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto px-4 py-4">
      <div className="mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Zap className="w-5 h-5 text-yellow-500" />
          Agent Chat
        </h1>
        <p className="text-sm text-muted-foreground">
          General-purpose AI assistant — papers, code, charts, search, all tools available
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 py-2 relative">
        <BranchDirectory
          paperId="0"
          activeConversationId={conversationId ? String(conversationId) : null}
          onSwitchConversation={switchConversation}
        />
        {loadingHistory ? (
          <div className="flex items-center justify-center mt-20 gap-2 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
            Loading history...
          </div>
        ) : messages.length === 0 ? (
          <div className="text-center text-muted-foreground mt-20">
            <Zap className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p className="text-lg font-medium">Agent Chat</p>
            <p className="text-sm">Full tool access: read papers, write code, draw charts, search arXiv</p>
          </div>
        ) : null}

        {messages.map((msg, i) => (
          <div key={i} className="space-y-2">
            {msg.role === "user" ? (
              <div className="flex justify-end">
                <div className="group relative bg-primary text-primary-foreground rounded-lg px-4 py-2 max-w-[80%]">
                  {editingIdx === i ? (
                    <div className="flex flex-col gap-2 min-w-[280px]">
                      <Textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        className="text-sm text-foreground bg-white dark:bg-gray-800 resize-none"
                        autoFocus
                        rows={2}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleEditSubmit(i); }
                          if (e.key === "Escape") { setEditingIdx(null); setEditText(""); }
                        }}
                      />
                      <div className="flex items-center gap-2 justify-end">
                        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => { setEditingIdx(null); setEditText(""); }}>Cancel</Button>
                        <Button size="sm" className="h-7 text-xs" onClick={() => handleEditSubmit(i)} disabled={!editText.trim() || isBranching}>Send</Button>
                      </div>
                    </div>
                  ) : (
                    msg.content
                  )}
                  {/* Edit button on hover */}
                  {editingIdx !== i && (
                    <button
                      onClick={() => { setEditingIdx(i); setEditText(msg.content); }}
                      className="absolute -bottom-5 right-1 p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                      title="Edit"
                    >
                      <Pencil className="size-3" />
                    </button>
                  )}
                  {/* Version nav */}
                  {conversationParentId && branchPointIndex > 0 && i === branchPointIndex && (
                    <button
                      onClick={() => switchConversation(conversationParentId)}
                      className="absolute -bottom-5 left-1 p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                      title="Back to parent"
                    >
                      <ChevronLeft className="size-3" />
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {/* Tool trace card */}
                {msg.trace.length > 0 && (
                  <Card className="p-2 border-l-4 border-l-blue-400 bg-blue-50/50 dark:bg-blue-950/20">
                    <button
                      onClick={() => toggleCollapse(i)}
                      className="flex items-center gap-1 text-xs font-medium text-blue-700 dark:text-blue-300 w-full"
                    >
                      {msg.collapsed ? (
                        <ChevronRight className="w-3 h-3" />
                      ) : (
                        <ChevronDown className="w-3 h-3" />
                      )}
                      <Wrench className="w-3 h-3" />
                      Thinking process ({msg.trace.length} step{msg.trace.length > 1 ? "s" : ""})
                    </button>

                    {!msg.collapsed && (
                      <div className="mt-2 space-y-1.5 text-xs">
                        {msg.trace.map((step, j) => (
                          <div key={j} className="border-t pt-1 first:border-0 first:pt-0">
                            <div className="flex items-center gap-1 font-mono">
                              <span className="text-blue-600 font-bold">[{step.step}]</span>
                              <span className="font-semibold">{step.tool.tool}</span>
                              <span className="text-muted-foreground truncate">
                                ({JSON.stringify(step.tool.params).slice(0, 80)})
                              </span>
                            </div>
                            {step.tool.observation && (
                              <details className="mt-0.5">
                                <summary className="text-muted-foreground cursor-pointer flex items-center gap-1">
                                  <Eye className="w-3 h-3" />
                                  Result ({step.tool.observation.length} chars)
                                </summary>
                                <pre className="mt-1 p-1.5 bg-muted rounded text-xs whitespace-pre-wrap max-h-32 overflow-y-auto">
                                  {step.tool.observation.slice(0, 1000)}
                                </pre>
                              </details>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </Card>
                )}

                {/* Answer with copy button */}
                {msg.content && (
                  <div className="group relative prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                    <button
                      onClick={() => { navigator.clipboard.writeText(msg.content); setCopiedIdx(i); setTimeout(() => setCopiedIdx(null), 2000); }}
                      className="absolute top-0 right-0 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                      title="Copy"
                    >
                      {copiedIdx === i ? <Check className="size-3 text-green-500" /> : <Copy className="size-3" />}
                    </button>
                  </div>
                )}

                {/* Streaming indicator */}
                {streaming && i === messages.length - 1 && !msg.content && (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {statusText}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t pt-3 mt-2">
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything: draw a chart, search papers, run code..."
            className="min-h-[60px] resize-none"
            disabled={streaming}
            rows={2}
          />
          <div className="flex flex-col gap-1">
            {streaming ? (
              <Button variant="destructive" size="sm" onClick={handleStop}>
                Stop
              </Button>
            ) : (
              <Button size="sm" onClick={handleSend} disabled={!input.trim()}>
                <FileText className="w-4 h-4 mr-1" />
                Send
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
