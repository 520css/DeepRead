export interface GuardInfo {
    failedPages: Set<string>;
    similarity: number | null;       // cosine similarity score, null if not computed
    similarityPassed: boolean;       // true if above threshold or not computed
    suspiciousNumbers: string[];     // numbers flagged by verify_numbers
    hasIssues: boolean;
    rawText: string;
}

const SIMILARITY_THRESHOLD = 0.70;

export function parseGuardResult(raw: string): GuardInfo {
    const info: GuardInfo = {
        failedPages: new Set(),
        similarity: null,
        similarityPassed: true,
        suspiciousNumbers: [],
        hasIssues: false,
        rawText: raw || "",
    };

    if (!raw) return info;

    // Split on double-newline to get individual warnings
    const parts = raw.split(/\n\n+/).filter(Boolean);

    for (const part of parts) {
        // Citation: "⚠️ 引用验证失败: 页码 3, 7 不在检索片段中。可能为幻觉。"
        const citationMatch = part.match(/引用验证失败.*?页码\s+([\d,\s]+)/);
        if (citationMatch) {
            const pages = citationMatch[1].split(/[,，]\s*/).map(s => s.trim());
            pages.forEach(p => info.failedPages.add(p));
            info.hasIssues = true;
        }

        // Similarity fail: "⚠️ 语义相似度偏低 (0.65 < 0.70)，回答可能与原文不符。"
        const simLowMatch = part.match(/语义相似度偏低.*?\(([\d.]+)\s*<\s*([\d.]+)\)/);
        if (simLowMatch) {
            info.similarity = parseFloat(simLowMatch[1]);
            info.similarityPassed = false;
            info.hasIssues = true;
        }

        // Similarity pass: "✅ 语义相似度: 0.82"
        const simOkMatch = part.match(/语义相似度:\s*([\d.]+)/);
        if (simOkMatch && !simLowMatch) {
            info.similarity = parseFloat(simOkMatch[1]);
            info.similarityPassed = info.similarity >= SIMILARITY_THRESHOLD;
        }

        // Numbers: "⚠️ 数值验证: 95.3, 1.2M 未在原文中找到，请核对。"
        const numMatch = part.match(/数值验证:\s*(.+?)\s*未在原文中找到/);
        if (numMatch) {
            info.suspiciousNumbers = numMatch[1].split(/[,，]\s*/).filter(Boolean);
            info.hasIssues = true;
        }
    }

    return info;
}

/** Count total citations in guard text */
export function countTotalCitations(raw: string): number {
    if (!raw) return 0;
    // Each "引用验证失败" means citations were checked
    const parts = raw.split(/\n\n+/).filter(Boolean);
    for (const part of parts) {
        const m = part.match(/引用验证/);
        if (m) {
            // Count failed + assume some passed
            const failed = (part.match(/\d+/g) || []).length;
            // We don't know total from guard text alone, approximate
            return failed > 0 ? failed : 0;
        }
    }
    return 0;
}
