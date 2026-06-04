---
name: translate
description: 将论文摘要或任意英文段落翻译成中文，并保留术语原文
model: deepseek-chat
---

# 翻译任务

将以下内容翻译成中文。规则：

1. 专业术语保留英文原文，用括号标注，例如：Transformer、self-attention（自注意力）
2. 保持原文的学术风格，不要口语化
3. 如果原文包含公式或引文标记 [P.X]，原样保留
4. 翻译结果用 Markdown 组织，分段清晰

---

{content}
