# Xcode - 终端原生 AI 编码 Agent

## 项目简介
Xcode 是一个终端原生的 AI 编码 Agent，提供工具调用、子 Agent 调度、计划模式、持久记忆等功能，通过审批优先的终端工作流实现本地编码自动化。

## 方向
方向一：Agentic AI 原生开发

## 技术栈
- AI IDE: Claude Code
- LLM: OpenAI 兼容 API（支持 DeepSeek、Claude 等）
- 框架: LangGraph（Agent 工作流）
- 语言: Python >= 3.10
- 容器: Docker（可选）

## 目录结构
```
cs599-project/
├── docs/                    # 项目文档
│   ├── architecture.md      # 详细架构说明
│   └── CS599_大作业报告.pdf  # 最终提交的报告
├── src/                     # 项目源代码
│   └── xcode_cli/          # 核心 CLI 模块
├── tests/                   # 测试代码
├── prompts/                 # Prompt 模板
├── examples/                # 示例配置
├── README.md
├── .gitignore
└── LICENSE
```

## 环境搭建

### 1. 依赖安装
```bash
# 克隆仓库
git clone https://github.com/你的用户名/cs599-project.git
cd cs599-project

# 安装依赖
pip install -e .
```

### 2. 环境变量配置
⚠️ 不要硬编码 API Key，使用以下方式配置：

**方式一：运行时配置**
```bash
xcode
/env set <your-api-key>
/env base-url <provider-base-url>
/env model <model-name>
```

**方式二：环境变量**
```bash
export XCODE_API_KEY=<your-api-key>
export XCODE_BASE_URL=<base-url>
export XCODE_MODEL=<model-name>
```

### 3. 启动步骤
```bash
xcode
```

## 核心功能
- 13 个内置工具：文件读写编辑、搜索、Shell、子 Agent 调度、任务跟踪、计划模式
- 流式 LLM 输出与工具调用（OpenAI 兼容 API）
- 审批优先工作流：写入/编辑/Shell 工具执行前需用户确认
- 项目/用户/自动记忆模型
- 上下文 Token 估算与自动压缩

## 项目状态
- [x] Proposal
- [x] MVP
- [x] Phase 1 - 核心工具与 Agent 循环
- [x] Phase 2 - MCP 集成与高级功能
- [x] Phase 3 - 稳定性与 Windows 兼容
- [ ] Final

## 开发工作流
- Spec-first：功能变更从规范文档开始
- TDD-core：高风险行为先写测试
- E2E-acceptance：终端原生行为在真实环境中验证

## License
MIT