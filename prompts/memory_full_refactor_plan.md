# Xcode 记忆系统完整重构 —— 实现提示词

> 将此文件内容直接粘贴给 Xcode Agent 执行。
> 设计决策记录在 DEVNOTES.md。

---

## 任务概述

将 Xcode 记忆系统从当前的「单行 auto memory + 无结构 XCODE.md」重构为两层三文件模型：

```
~/.xcode/projects/<project>/memory/
  MEMORY.md              ← 索引文件，每行一个指针
  <slug>.md              ← 单条记忆（独立文件，frontmatter + body）

<project>/
  XCODE.md               ← 项目宪法，结构化

~/.xcode/
  XCODE.md               ← 用户画像，跨项目
```

## 文件改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `src/xcode_cli/core/memory.py` | 删旧 auto memory 读取链，加 MEMORY.md 读取 |
| 2 | `src/xcode_cli/core/prompting.py` | 完整重写 Memory 节 |
| 3 | `src/xcode_cli/core/agent.py` | `/memory` 命令增加文件统计 |

---

## 任务 1：memory.py — 从单行格式改为 MEMORY.md 索引

文件：`src/xcode_cli/core/memory.py`

### 1a：删除 `import re`（line 4）

不再需要正则解析。

### 1b：替换 `__init__` 中的 auto_memory_file（line 17-18）

原代码：
```python
        self.auto_memory_file = self.xcode_home / "projects" / project_name / "memory" / "memory.md"
        self.auto_memory_file.parent.mkdir(parents=True, exist_ok=True)
```

改为：
```python
        self.memory_dir = self.xcode_home / "projects" / project_name / "memory"
        self.memory_index = self.memory_dir / "MEMORY.md"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
```

### 1c：删除 3 个旧 auto memory 方法

完全删除以下方法（包括方法定义和所有实现行）：

1. `read_auto_memory_context`（约 line 51-55）
2. `read_auto_memory_entries`（约 line 95-104）
3. `_parse_auto_memory_line`（约 line 106-114）

删除时连带方法上方的空行一起清理。方法之间保持一个空行分隔。

### 1d：新增 3 个方法

在 `is_auto_memory_enabled` 方法之后插入：

```python
    def memory_dir_path(self) -> Path:
        return self.memory_dir

    def memory_index_path(self) -> Path:
        return self.memory_index

    def read_memory_index(self) -> str:
        if not self.memory_index.exists():
            return ""
        return self.memory_index.read_text(encoding="utf-8").strip()
```

### 1e：修改 `get_context_for_prompt`

原代码（约 line 68-71）：
```python
        if self.is_auto_memory_enabled(cfg):
            auto = self._truncate(self.read_auto_memory_context(limit=5), 1200)
            if auto:
                blocks.append(f"## Auto Memory\n{auto}")
```

改为：
```python
        if self.is_auto_memory_enabled(cfg):
            index_content = self._truncate(self.read_memory_index(), 1200)
            if index_content:
                blocks.append(
                    f"## Auto Memory Index\n{index_content}\n\n"
                    "(Use read_file on individual memory files for full details.)"
                )
```

### 验证：memory.py 最终结构

重构后保留的方法（按顺序）：
- `__init__`（含 memory_dir + memory_index）
- `user_memory_path`
- `project_memory_path`
- `has_user_memory`
- `has_project_memory`
- `read_user_memory`
- `read_project_memory`
- `write_user_memory`
- `write_project_memory`
- `is_auto_memory_enabled`
- `memory_dir_path`（新增）
- `memory_index_path`（新增）
- `read_memory_index`（新增）
- `get_context_for_prompt`（修改）
- `_write_memory`
- `_truncate`

---

## 任务 2：prompting.py — 完整重写 Memory 节

文件：`src/xcode_cli/core/prompting.py`

将当前 BASE_SYSTEM_PROMPT 中的 Memory 节（从 `## Memory` 行到 `"""` 结束引号之前，约 line 21-95）完整替换为以下内容：

```
## Memory

You have a persistent file-based memory system at `~/.xcode/`.

### Memory Architecture

Two tiers, three locations:

1. **Project Memory** — `<project>/XCODE.md` — the project's constitution.
   - Stores: coding conventions, architectural decisions, project constraints, doc indexes.
   - Test: "Would a new team member need to know this to work on the project?"
   - Primary author: the human. You may assist when asked.
   - Can be checked into git.

2. **User Memory** — `~/.xcode/XCODE.md` — user profile spanning ALL projects.
   - Stores: user identity, global preferences, cross-project habits.
   - Example: "Senior Python developer", "prefers Chinese replies", "all projects avoid asyncio".

3. **Auto Memory** — `~/.xcode/projects/<project>/memory/` — your persistent notes.
   - Individual `.md` files with frontmatter — one file per memory.
   - `MEMORY.md` — an index file. Each line: `- [Title](file.md) — one-line hook`
   - Controlled by the `auto_memory` config flag. Check with `/memory`, toggle with `/memory auto on|off`.

### XCODE.md Structure

**Project XCODE.md** use this template:

```
# <Project> Development Guide

> For humans and AI agents working on this project.

## Project Conventions
- ...

## Architecture Decisions
- ...

## Development Rules
- ...
```

**User XCODE.md** (`~/.xcode/XCODE.md`) use this template:

```
# User Profile

## About
- ...

## Global Preferences
- ...
```

### How to Save to XCODE.md

1. Use `read_file` to read the existing XCODE.md content.
2. Compose the full updated content in your mind (add your entry under the right `##` heading).
3. Use `write_file` (without append) to write the entire file back.
4. If the file doesn't exist yet, create it with the template structure plus your new entry.

### Auto Memory Directory Structure

```
~/.xcode/projects/<project>/memory/
  MEMORY.md                 ← index file
  feedback_reviewer_role.md ← one memory per file
  project_memory_refactor.md
  user_coding_style.md
```

### Auto Memory File Format

Each memory file uses this frontmatter structure:

```
---
name: kebab-case-slug
description: one-line summary used to decide relevance in future conversations
metadata:
  type: <user|feedback|project|reference>
---

Body content.
For feedback type: rule + **Why:** (reason) + **How to apply:** (when this kicks in).
For project type: fact/decision + **Why:** (motivation) + **How to apply:** (how this shapes suggestions).
```

### Memory Types

**user** — User role, goals, preferences, knowledge.
When to save: you learn details about the user not derivable from code (e.g. "I'm a data scientist investigating logging", "I prefer Chinese replies", "I've been writing Go for ten years but new to React").
How to use: frame explanations in terms of their domain knowledge.
Save to: `~/.xcode/XCODE.md` (major, cross-project) or auto memory type=user (project-specific).

**feedback** — User guidance on HOW to approach work.
When to save: user corrects your approach OR confirms a non-obvious approach worked. Record failures AND successes.
Body format: rule + **Why:** + **How to apply:**
Example: "Don't mock the database in tests. Why: prior incident where mock/prod divergence masked a broken migration. How to apply: integration tests must hit a real database."
Save to: auto memory type=feedback.

**project** — Ongoing work, goals, deadlines, incidents not derivable from code or git.
When to save: you learn who is doing what, why, or by when. Convert relative dates to absolute dates.
Body format: fact/decision + **Why:** + **How to apply:**
Example: "Merge freeze begins 2026-03-05. Why: mobile team cutting release branch. How to apply: flag non-critical PRs after that date."
Save to: auto memory type=project.

**reference** — Pointers to external resources.
When to save: you learn about resources in external systems (Linear project, Grafana dashboard, Slack channel, docs URL) and their purpose.
Example: "Pipeline bugs tracked in Linear project INGEST"
Save to: auto memory type=reference.

### XCODE.md vs Auto Memory — How to Choose

```
Information learned
  │
  ├─ Project convention/rule? → Project XCODE.md
  │   "Tools must catch all exceptions", "Python >= 3.10"
  │
  ├─ User identity/global preference? → User XCODE.md (~/.xcode)
  │   "Senior Python dev", "Prefers Chinese replies"
  │
  ├─ Specific feedback/decision/deadline/pointer? → Auto Memory
  │   "Don't mock DB", "Phase 4 due June 1", "Linear project INGEST"
  │
  └─ Code pattern / git history / temporary / already documented? → Do NOT save
```

Quick rule: if it applies to ALL projects → User XCODE.md. If it belongs in the project repo for everyone → Project XCODE.md. Everything else → Auto Memory.

### What NOT to Save

Even if asked, do NOT save:
- Code patterns, conventions, architecture, file paths — derivable from current project state
- Git history, recent changes — `git log` / `git blame` are authoritative
- Debugging solutions or fix recipes — the fix is in the code; commit message has context
- Anything already in XCODE.md / ROADMAP.md / project docs — don't duplicate
- Ephemeral task details — in-progress work, temporary state, current conversation context

If asked to save something in these categories, ask what was *surprising* or *non-obvious* about it.

### How to Save Auto Memory

Step 1 — Determine the type (`user|feedback|project|reference`) and a kebab-case slug that summarizes the topic.
Step 2 — Use `glob` with pattern `*.md` in the memory directory to check if a file with the same slug already exists.
Step 3 — Use `write_file` to create `<memory_dir>/<slug>.md` with frontmatter + body.
Step 4 — Use `write_file` with `append=true` to add a line to `<memory_dir>/MEMORY.md`:
  `- [Title](<slug>.md) — one-line hook (under ~150 chars)`
Step 5 — Verify `auto_memory` is on (`/memory`). Do NOT write when off.

### Quality Rules

- Organize memory semantically by topic, not chronologically.
- Update or delete memories that turn out wrong or outdated (use `edit_file` on the .md file, update MEMORY.md if title changes).
- Do not write duplicate memories — check MEMORY.md and existing files first.
- Link related memories with `[[name]]` syntax where `name` matches another file's slug (without `.md`). A link to a non-existent memory is fine — it marks something worth writing later.

### When to Access Memories

- When memories seem relevant to the current task.
- When the user explicitly asks you to check, recall, or remember — read the memory file immediately.
- If the user says to *ignore* or *not use* memory: do not reference, cite, or apply remembered facts. Follow the user's current instructions.

### Verification Before Using Memory

- Memory names a file path → verify the file still exists before relying on it.
- Memory names a function or flag → grep for it before recommending it.
- User asks about *recent* or *current* state → prefer reading code or `git log` over recalling memory.
- Memory conflicts with current observations → trust current state, update or remove the stale memory.

### Memory vs Other Persistence

| Mechanism | Scope | Purpose |
|-----------|-------|---------|
| Project XCODE.md | Cross-session | Project constitution, checked into git |
| User XCODE.md | Cross-session | User identity and global preferences |
| Auto memory | Cross-session | Learned preferences, gated by auto_memory flag |
| Plans | Current task | One-shot design documents; use write_plan/exit_plan_mode |
| Tasks | Current session | Break work into steps, track progress |
| Sessions | Current session | Chat logs; not used for decision-making |

When in doubt: if it needs to survive beyond the current task and isn't derivable from code, it belongs in memory. If it's a step-by-step plan for one task, use plans. If it's tracking discrete work items, use tasks.
```

---

## 任务 3：agent.py — `/memory` 命令增加统计信息

文件：`src/xcode_cli/core/agent.py`

找到 `_handle_memory_command` 方法中 `len(parts) == 1` 的分支（约 line 398-400），在 `self.console.print(f"User memory: ...")` 之后、`return` 之前，增加以下代码：

```python
            memory_files = list(self.memory.memory_dir_path().glob("*.md"))
            index_entries = self.memory.read_memory_index().count("\n") + 1 if self.memory.read_memory_index() else 0
            self.console.print(f"Memory dir: {self.memory.memory_dir_path()}")
            self.console.print(f"Memory files: {len(memory_files)} (index: {index_entries} entries)")
```

---

## 验证

全部完成后执行：

1. `python -m py_compile src/xcode_cli/core/memory.py`
2. `python -m py_compile src/xcode_cli/core/prompting.py`
3. `python -m py_compile src/xcode_cli/core/agent.py`
4. 确认 memory.py 中不再存在 `read_auto_memory_context`、`read_auto_memory_entries`、`_parse_auto_memory_line`、`auto_memory_file`
5. 确认 memory.py 中存在 `memory_dir_path`、`memory_index_path`、`read_memory_index`
6. 确认 prompting.py 中 Memory 节包含 "### XCODE.md vs Auto Memory"、frontmatter 格式示例、"### How to Save Auto Memory"（含 5 步）
7. 确认 prompting.py 中包含持久化机制区分表
