---
name: explain
model: claude-sonnet-4-6
temperature: 0.2
max_tokens: 1500
---
Explain the following term or passage from an academic paper.

Context passage:
{context}

Term/passage to explain:
{target}

Hard rules:

1. Base explanation ONLY on the provided context.
2. Cite with [P.X] where X is the page number.
3. Do not introduce external knowledge.

Answer in {user_language}. Adapt depth for a {user_level} in {user_field}.
