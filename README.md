# Xcode — 终端原生 AI 编码 Agent

终端原生的 AI 编码 Agent，支持工具调用、子 Agent 调度、计划模式、持久记忆，通过审批优先的工作流实现本地编码自动化。

## 技术栈

| 层级 | 选型 |
|------|------|
| LLM | OpenAI 兼容 API（DeepSeek、Claude 等） |
| Agent 框架 | LangGraph |
| 语言 | Python ≥ 3.10 |
| CLI | Typer + Rich + prompt-toolkit |
| 工具协议 | MCP (Model Context Protocol) |

## 核心能力

**13 个内置工具** — 文件读写编辑、grep/glob 搜索、Shell 执行、子 Agent 调度、任务跟踪、计划模式、Skill 调用

**MCP 集成** — 通过 `.xcode/mcp.json` 配置接入任意 MCP stdio 工具服务器，支持信任网关、动态工具刷新、生命周期事件追踪、per-tool 输出限制

**Skill 系统** — 5 层架构（数据模型 → 加载校验 → 调用服务 → 工具注册 → 执行），用户通过 `/skill` 斜杠命令调用，LLM 通过 `skill()` 工具自主调用，支持反递归与会话审计

**QQ Chat** — 通过 QQ Bot WebSocket 网关接入，在 QQ 上与 Xcode 对话。独立会话（不污染终端历史），4 层安全策略（工具黑名单 → Schema 可见性 → 执行白名单 + 只读检查 → 权限 + 远程审批），远程会话默认只读

**记忆系统** — 三级持久记忆：项目级 `XCODE.md`（团队共享）、用户级 `~/.xcode/XCODE.md`（跨项目偏好）、自动记忆（自动学习的反馈与决策）

**上下文管理** — Token 估算与自动压缩，支持 `/compact` 和 `/resume`

## 目录结构

```
cs599-project/
├── docs/                        # 架构文档
├── src/xcode_cli/               # 源代码
│   ├── core/                    #   Agent 运行时、工具、权限、UI
│   ├── skills/                  #   Skill 子系统（5 层）
│   ├── mcp/                     #   MCP 子系统（10 模块）
│   └── qqchat/                  #   QQ Chat 子系统（7 模块）
├── tests/                       # 测试
├── prompts/                     # Prompt 模板
└── examples/                    # 示例配置与 Skill
```

## 快速开始

### 安装

```bash
git clone https://github.com/你的用户名/cs599-project.git
cd cs599-project
pip install -e .
```

### 配置 API

**运行时配置（推荐）**
```bash
xcode
/env set <your-api-key>
/env base-url <provider-base-url>
/env model <model-name>
```

**环境变量**
```bash
export XCODE_API_KEY=<your-api-key>
export XCODE_BASE_URL=<base-url>
export XCODE_MODEL=<model-name>
```

### 启动

```bash
xcode
```

### 接入 MCP 工具服务器

在项目根目录创建 `.xcode/mcp.json`：
```json
{
  "mcpServers": {
    "my-server": {
      "command": "python",
      "args": ["path/to/server.py"]
    }
  }
}
```

启动后 Xcode 自动发现并注册 MCP 工具，可通过 `/mcp status` 查看状态。

### 接入 QQ Chat

在 `.xcode/qqchat.json` 中配置 QQ Bot 凭证后，运行 `/qqchat start` 即可在 QQ 上与 Xcode 对话。

## 开发工作流

以 **SDD（Specification-Driven Development）** 为主导：

1. **Spec-first** — 功能变更从规范文档开始，`docs/architecture.md` 作为活文档持续维护
2. **TDD-core** — 高风险行为先写测试，`tests/` 覆盖 50+ 测试文件
3. **验证驱动** — 终端原生行为在真实环境中端到端验证

## 项目状态

- [x] Proposal
- [x] MVP
- [x] Phase 1 — 核心工具与 Agent 循环
- [x] Phase 2 — MCP 集成与高级功能
- [x] Phase 3 — 稳定性与 Windows 兼容
- [ ] Final

## License

MIT