---
name: summary
model: claude-sonnet-4-6
temperature: 0.3
max_tokens: 2000
---

Summarize the following academic paper concisely.

Output format:
1. One-sentence summary: the core contribution.
2. Key contributions: 3-5 bullet points.
3. Method overview: research type + dataset + key metric.
4. Key results: most important findings with exact numbers.
5. Limitations and future work.

Hard rules:
- Every claim must cite [P.X] where X is the page number.
- Do not fabricate any information.
- If a section is unclear in the paper, state "原文未明确说明".

Paper content:
{paper_content}

Answer in {user_language}. The user is a {user_level} in {user_field}.
