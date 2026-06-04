# DeepRead 架构设计文档

## 整体架构

```
┌─────────────────────────────────────────────────────┐
│                    前端 (Next.js)                    │
│  PDF 阅读器 │ 对话面板 │ 标注系统 │ Agent Chat │      │
└────────────────────┬────────────────────────────────┘
                     │ HTTP + SSE
┌────────────────────┴────────────────────────────────┐
│                  后端 (FastAPI)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │ API 路由  │ │ 服务层   │ │     Agent 引擎        │ │
│  │ papers   │ │ chat     │ │  loop.py (ReAct)     │ │
│  │ messages │ │ paper    │ │  react_prompt.py     │ │
│  │ highlights│ │ highlight│ │  tool_registry.py   │ │
│  │ agent    │ │ memory   │ │  context.py (压缩)   │ │
│  └──────────┘ └──────────┘ └──────────────────────┘ │
│                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐ │
│  │ 核心模块  │ │ 数据层   │ │     工具层            │ │
│  │ embedder │ │ SQLite   │ │ read/search/compare  │ │
│  │ guard    │ │ ChromaDB │ │ note/skill/run       │ │
│  │ rag      │ │          │ │                      │ │
│  │ parser   │ │          │ │                      │ │
│  └──────────┘ └──────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Agent 引擎

### ReAct 循环

```
用户提问 → 加载历史 → 上下文压缩(如需要)
    ↓
┌─────────────────────────────┐
│  循环 (最多 10 轮)           │
│  1. LLM 调用 → 解析响应      │
│  2. 有 <tool_call> ?        │
│     → 执行工具 → 追加结果    │
│     → 标记 is_error → 继续   │
│  3. 有 <answer> ?           │
│     → 提取答案 → 流式输出    │
│     → Guard 检测            │
│     → 反思生成               │
│     → 保存消息               │
└─────────────────────────────┘
```

### 工具系统

| 工具 | 功能 | 关键参数 |
|------|------|---------|
| `read` | 论文 RAG 检索 / 文件读取 | paper_id, query, path |
| `search` | 本地 ChromaDB / arXiv 搜索 | query, scope |
| `compare` | 多论文并行对比 | paper_ids, dimension |
| `note` | 保存 Markdown 笔记 | content, target, tags |
| `skill` | 加载技能模板 | name |
| `run` | 执行 Python 代码/脚本 | code, script |

### 自我反思

每次任务完成后，反思模块分析工具调用记录，生成改进建议。采用三层存储：

- **Hot**：最近 5 条反思加载到 system prompt（≤800 字）
- **Warm**：旧反思合并为 `_digest.md` 摘要
- **收敛**：文件数 > 10 自动合并，> 20 清理旧文件

### Skill 系统

支持两种格式：

1. **单文件**（`skills/xxx.md`）：YAML 头 + Markdown 指令
2. **目录包**（`skills/xxx/SKILL.md` + `scripts/` + `references/`）

Agent 调用 `skill(name="xxx")` 加载完整指令，可配合 `run(script=...)` 执行技能脚本。

## PDF 解析管线

```
上传 PDF
    ↓
┌─────────────────────┐
│ PyMuPDF 快速解析     │ → 即时可用，页面级文本
│ (quick parse)       │
└─────────────────────┘
    ↓
┌─────────────────────┐
│ Marker 验证级解析    │ → 后台线程，结构化 Markdown
│ (verified parse)    │   分页 + 图片提取 + 元数据
└─────────────────────┘
    ↓
┌─────────────────────┐
│ smart_chunk + RAG   │ → 每页上限 80 chunks，分批嵌入
│ ChromaDB 索引        │
└─────────────────────┘
```

## 幻觉检测

三层 Guard：

1. **引用验证**：检查 `[P.X]` 页码是否在检索 chunk 中
2. **语义相似度**：回答 vs 检索结果的余弦相似度（bge-large-en-v1.5）
3. **数值校验**：回答中的数字是否在原文中出现

检测结果在每条 AI 回复底部显示，支持 👍👎 用户反馈。

## 树状对话

基于 `conversations.parent_id` 自引用实现对话级别分支：

```
对话 A (根)
├── 对话 B (编辑 msg3 → 分支)    parent_id = A
│   └── 对话 C (再次编辑)        parent_id = B
└── 对话 D (编辑 msg5 → 分支)    parent_id = A
```

- 编辑任意用户消息 → 自动创建分支对话
- 前缀消息复用，编辑点之后独立发展
- ← → 按钮在分支点切换版本
- 右下角浮动目录显示所有分支点

## 数据存储

| 数据 | 存储 | 说明 |
|------|------|------|
| 论文元数据 | SQLite `papers` | 标题、作者、摘要、解析状态 |
| 对话消息 | SQLite `conversations` + `messages` | 树状结构、guard_result |
| PDF 文本块 | SQLite `chunks` + ChromaDB | 每页 ≤80 chunks |
| 高亮标注 | SQLite `highlights` | 位置坐标、颜色、笔记 |
| LLM 用量 | SQLite `llm_usage` | 按 provider 统计费用 |
| 反思记录 | `storage/agent_reflections/` | 自动收敛 |
| 用户记忆 | `storage/memory/user.md` | Agent 偏好注入 |

## LLM 路由

统一路由支持多 Provider，自动 fallback：

```python
router.complete(messages, provider="deepseek")
    ↓ 失败
router.complete(messages, provider="claude")   # fallback 1
    ↓ 失败
router.complete(messages, provider="openai")   # fallback 2
```

预算控制：月度限额，超额自动降级或阻断。

## 上下文管理

- **上下文窗口**：DeepSeek 64K token
- **触发压缩**：总 token > 80%（≈51K）时触发
- **压缩策略**：保留最近 4 轮 + system prompt，旧消息压缩为 300 字中文摘要
- **反思上限**：System prompt 中反思块 ≤800 字
- **Skill 渐进加载**：System prompt 只含名称+描述，Agent 调用时才加载全文
