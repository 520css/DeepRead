"use client";

import React from "react";

interface CitationWrapperProps {
    children: React.ReactNode;
    handleCitationClick: (key: string, messageIndex: number, searchText?: string) => void;
    messageIndex: number;
}

// Match: (P.3), [P.3], （P.3） with optional English text in quotes: (P.3, "the core idea")
const CITATION_REGEX = /[\[\(（](P\.)(\d+(?:-\d+)?)(?:[,，]\s*P\.\d+(?:-\d+)?)*(?:\s*[,，]\s*["“”]([^"“”]{3,200})["“”])?[\]\)）]/gi;

function processText(text: string, handleCitationClick: (key: string, messageIndex: number, searchText?: string) => void, messageIndex: number): React.ReactNode {
    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    const regex = new RegExp(CITATION_REGEX.source, CITATION_REGEX.flags);
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) {
        if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
        const prefix = (match[1] || "").toUpperCase() === "P." ? "P." : (match[1] || "");
        const capturedNum = match[2];
        const searchText = match[3] || ""; // optional English snippet for PDF search
        const pageNum = (capturedNum || "?").split("-")[0];
        // Display only (P.X) visually; full text in title tooltip
        const displayLabel = (prefix + capturedNum).replace(/^(.)/, (prefix.startsWith("P") ? "(" : "[") + prefix + capturedNum + (prefix.startsWith("P") ? ")" : "]"));
        parts.push(React.createElement("span", {
            key: `cit-${match.index}`,
            className: "inline-block bg-secondary text-secondary-foreground rounded px-1 text-xs font-medium cursor-pointer hover:bg-primary/20 hover:text-primary transition-colors align-baseline",
            onClick: (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); handleCitationClick(prefix + capturedNum, messageIndex, searchText || undefined); },
            title: searchText ? "Jump to page " + pageNum + ": " + searchText : "Jump to page " + pageNum,
        }, displayLabel));
        lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) parts.push(text.slice(lastIndex));
    return parts.length > 0 ? parts : text;
}

export function CitationWrapper({ children, handleCitationClick, messageIndex }: CitationWrapperProps) {
    if (typeof children === "string") {
        return React.createElement(React.Fragment, null, processText(children, handleCitationClick, messageIndex));
    }
    const mapped = React.Children.map(children, (child) => {
        if (typeof child === "string") return processText(child, handleCitationClick, messageIndex);
        return child;
    });
    return React.createElement(React.Fragment, null, mapped);
}
