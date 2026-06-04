---
name: obsidian
description: Read, write, and search notes in the Obsidian vault at D:/research_agent/notes
---
# Obsidian Vault

Vault path: `D:/research_agent/notes`

## 读取笔记

```
read(path="D:/research_agent/notes/agent_notes/笔记名.md")
```

## 列出 / 搜索笔记

```
run(code="import glob; print('\n'.join(glob.glob('D:/research_agent/notes/agent_notes/**/*.md', recursive=True)))")
```

## 创建笔记

```
run(code="open('D:/research_agent/notes/agent_notes/新笔记.md', 'w', encoding='utf-8').write('''Markdown 内容''')")
```

## 追加笔记

```
run(code="""
with open('D:/research_agent/notes/agent_notes/笔记.md', 'r', encoding='utf-8') as f:
    old = f.read()
with open('D:/research_agent/notes/agent_notes/笔记.md', 'w', encoding='utf-8') as f:
    f.write(old + '\n## 新章节\n...')
""")
```

## 规则

- 所有读写必须用 vault 完整路径
- 优先用 `read(path=...)` 读取，`run(code=...)` 写入
- 笔记名用中文或英文，不加特殊字符
