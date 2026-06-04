"use client";

import { useCallback, useEffect, useState } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { Link } from "@tiptap/extension-link";
import { Image as ImageExt } from "@tiptap/extension-image";
import { Underline } from "@tiptap/extension-underline";
import { TextAlign } from "@tiptap/extension-text-align";
import { Highlight } from "@tiptap/extension-highlight";
import { Typography } from "@tiptap/extension-typography";
import { Color } from "@tiptap/extension-color";
import { TextStyle } from "@tiptap/extension-text-style";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { Mathematics, InlineMath } from "@tiptap/extension-mathematics";
import { fetchFromApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card } from "@/components/ui/card";
import { Loader2, Plus, Sparkles, Trash2, FileText } from "lucide-react";
import "katex/dist/katex.min.css";

// ─── Component ───

interface Note {
    id: string;
    paper_id: string;
    content: string;
    highlights: number[];
    tags: string[];
    created_at: string;
    updated_at: string;
}

interface NotesPanelProps {
    paperId: string;
    paperTitle?: string;
}

export function NotesPanel({ paperId, paperTitle: _title }: NotesPanelProps) {
    const [notes, setNotes] = useState<Note[]>([]);
    const [activeNoteId, setActiveNoteId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);
    const [saving, setSaving] = useState(false);

    const editor = useEditor({
        immediatelyRender: false,
        extensions: [
            StarterKit.configure({ heading: { levels: [1, 2, 3, 4] } }),
            Placeholder.configure({ placeholder: "Write notes in Markdown...  $\\LaTeX$  |  ==highlight==  |  [link](url)" }),
            Link.configure({ openOnClick: true, HTMLAttributes: { class: "text-blue-500 underline" } }),
            ImageExt.configure({ allowBase64: true, inline: true }),
            Underline,
            TextAlign.configure({ types: ["heading", "paragraph"] }),
            Highlight.configure({ multicolor: true }),
            Typography,
            TextStyle,
            Color,
            Table.configure({ resizable: true }),
            TableRow,
            TableCell,
            TableHeader,
            Mathematics,
            InlineMath,
        ],
        content: "",
    });

    // ─── Load notes ───
    const loadNotes = useCallback(async () => {
        setLoading(true);
        try {
            const data = await fetchFromApi(`/api/annotation?paper_id=${paperId}`);
            setNotes(Array.isArray(data) ? data : []);
        } catch {
            setNotes([]);
        } finally {
            setLoading(false);
        }
    }, [paperId]);

    useEffect(() => {
        loadNotes();
    }, [loadNotes]);

    const selectNote = useCallback((note: Note) => {
        setActiveNoteId(note.id);
        editor?.commands.setContent(note.content || "");
    }, [editor]);

    const createNote = useCallback(async () => {
        try {
            const res = await fetchFromApi("/api/annotation", {
                method: "POST",
                body: JSON.stringify({ paper_id: parseInt(paperId), content: "", tags: [] }),
            });
            await loadNotes();
            setActiveNoteId(String(res.id));
            editor?.commands.setContent("");
        } catch (e) {
            console.error("Create note failed:", e);
        }
    }, [paperId, editor, loadNotes]);

    const saveNote = useCallback(async () => {
        if (!activeNoteId || !editor) return;
        setSaving(true);
        try {
            const content = editor.getHTML();
            await fetchFromApi(`/api/annotation/${activeNoteId}`, {
                method: "PATCH",
                body: JSON.stringify({ content }),
            });
            await loadNotes();
        } catch (e) {
            console.error("Save failed:", e);
        } finally {
            setSaving(false);
        }
    }, [activeNoteId, editor, loadNotes]);

    const deleteNote = useCallback(async (noteId: string) => {
        try {
            await fetchFromApi(`/api/annotation/${noteId}`, { method: "DELETE" });
            if (activeNoteId === noteId) {
                setActiveNoteId(null);
                editor?.commands.setContent("");
            }
            await loadNotes();
        } catch (e) {
            console.error("Delete failed:", e);
        }
    }, [activeNoteId, editor, loadNotes]);

    const generateNote = useCallback(async () => {
        setGenerating(true);
        try {
            const res = await fetchFromApi("/api/notes/generate", {
                method: "POST",
                body: JSON.stringify({ paper_id: parseInt(paperId) }),
            });
            const content = res.content || res.note || "";
            const createRes = await fetchFromApi("/api/annotation", {
                method: "POST",
                body: JSON.stringify({ paper_id: parseInt(paperId), content, tags: ["ai-generated"] }),
            });
            await loadNotes();
            setActiveNoteId(String(createRes.id));
            editor?.commands.setContent(content);
        } catch (e) {
            console.error("Generate failed:", e);
        } finally {
            setGenerating(false);
        }
    }, [paperId, editor, loadNotes]);

    useEffect(() => {
        const h = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveNote(); }
        };
        window.addEventListener("keydown", h);
        return () => window.removeEventListener("keydown", h);
    }, [saveNote]);

    return (
        <div className="flex flex-col h-full">
            {/* Toolbar */}
            <div className="flex items-center gap-1.5 p-2 border-b shrink-0">
                <Button variant="ghost" size="sm" onClick={createNote}><Plus size={14} className="mr-1" />New</Button>
                <Button variant="ghost" size="sm" onClick={generateNote} disabled={generating}>
                    {generating ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Sparkles size={14} className="mr-1" />}
                    Generate
                </Button>
                <Button variant="ghost" size="sm" onClick={() => editor?.chain().focus().toggleBold().run()} title="Bold">B</Button>
                <Button variant="ghost" size="sm" onClick={() => editor?.chain().focus().toggleItalic().run()} title="Italic"><i>I</i></Button>
                <Button variant="ghost" size="sm" onClick={() => editor?.chain().focus().toggleStrike().run()} title="Strikethrough"><s>S</s></Button>
                <Button variant="ghost" size="sm" onClick={() => editor?.chain().focus().toggleHighlight().run()} title="Highlight"><span className="bg-yellow-300 px-1">H</span></Button>
                <div className="flex-1" />
                {activeNoteId && (
                    <Button variant="ghost" size="sm" onClick={saveNote} disabled={saving}>
                        {saving ? <Loader2 size={14} className="mr-1 animate-spin" /> : null}Save
                    </Button>
                )}
            </div>

            {/* Body */}
            <div className="flex flex-1 min-h-0">
                <div className="w-36 border-r shrink-0">
                    <ScrollArea className="h-full">
                        <div className="p-1 space-y-0.5">
                            {loading ? (
                                <div className="flex justify-center py-4"><Loader2 size={16} className="animate-spin text-muted-foreground" /></div>
                            ) : notes.length === 0 ? (
                                <p className="text-xs text-muted-foreground p-2 text-center">No notes yet</p>
                            ) : (
                                notes.map((note) => (
                                    <Card
                                        key={note.id}
                                        className={`p-1.5 cursor-pointer text-xs group transition-colors ${
                                            activeNoteId === note.id ? "ring-1 ring-blue-400 bg-blue-50 dark:bg-blue-950" : "hover:bg-accent"
                                        }`}
                                        onClick={() => selectNote(note)}
                                    >
                                        <div className="flex items-start justify-between gap-1">
                                            <div className="line-clamp-2 flex-1 text-muted-foreground">
                                                {stripHtml(note.content) || "Empty note"}
                                            </div>
                                            <button
                                                className="opacity-0 group-hover:opacity-100 shrink-0 text-red-400 hover:text-red-600"
                                                onClick={(e) => { e.stopPropagation(); deleteNote(note.id); }}
                                            ><Trash2 size={10} /></button>
                                        </div>
                                        <div className="text-[10px] text-muted-foreground/60 mt-1">{note.updated_at?.slice(0, 10)}</div>
                                    </Card>
                                ))
                            )}
                        </div>
                    </ScrollArea>
                </div>

                <div className="flex-1 min-w-0 overflow-hidden">
                    {activeNoteId ? (
                        <div className="h-full overflow-y-auto p-3">
                            <EditorContent
                                editor={editor}
                                className="prose prose-sm dark:prose-invert max-w-none
                                    [&_.ProseMirror]:min-h-[200px] [&_.ProseMirror]:outline-none [&_.ProseMirror]:text-sm
                                    [&_.ProseMirror_table]:border-collapse [&_.ProseMirror_th]:border [&_.ProseMirror_th]:border-gray-300 [&_.ProseMirror_th]:px-2 [&_.ProseMirror_th]:py-1 [&_.ProseMirror_th]:bg-gray-100
                                    [&_.ProseMirror_td]:border [&_.ProseMirror_td]:border-gray-300 [&_.ProseMirror_td]:px-2 [&_.ProseMirror_td]:py-1"
                            />
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                            <div className="text-center space-y-2">
                                <FileText size={24} className="mx-auto opacity-30" />
                                <p>Select a note or create one</p>
                                <Button variant="outline" size="sm" onClick={generateNote} disabled={generating}>
                                    {generating ? <Loader2 size={14} className="mr-1 animate-spin" /> : <Sparkles size={14} className="mr-1" />}
                                    AI Generate
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function stripHtml(html: string): string {
    if (!html) return "";
    return html.replace(/<[^>]*>/g, "").substring(0, 100);
}
