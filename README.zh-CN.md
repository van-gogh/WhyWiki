# WhyWiki

[English](README.md) | [简体中文](README.zh-CN.md)

**记住“为什么”的团队 Wiki。** ✨

Git 记住改了什么。WhyWiki 记住为什么改。

WhyWiki 会把分散的项目材料整理成一个持续更新、带证据的 Wiki，适合混乱的软件项目：需求、代码、决策、冲突、实验、部署记录和交接上下文，都放在一个本地工作区里。

它面向小团队、实验室、开源维护者和独立开发者，帮助回答这些反复出现的问题：

- “哪个需求才是当前有效的？”
- “我们为什么这样实现？”
- “这个决策来自哪里？”
- “哪些内容变了，哪些说明已经不同步？”
- “怎样把项目交给下一个人，而不丢掉上下文？”

## WhyWiki 能做什么

WhyWiki 读取本地文件、文档、代码和 Git 仓库，然后构建一份可检查的项目记忆：

- 🔎 **有来源支撑的内容块**，来自 Markdown、文本、CSV、代码、PDF、DOCX 和 XLSX
- 🧠 **项目事实**，从材料中提取，并且每条都带证据
- ⚠️ **冲突报告**，覆盖过期文档、API 不一致、缺失文件，以及模型/部署漂移
- 📚 **Wiki 页面**，基于证据生成，而不是凭感觉编写
- 📦 **交接包**，用于新人上手、审计和项目移交
- 💬 **带证据的问答**，回答会指回真实文件

WhyWiki 不打算替代 Git、Notion、Confluence、飞书、GitHub 或 issue tracker。它放在这些工具旁边，专门记住那些通常会从系统里流失的项目知识。

```text
local files / git repo / docs / code
  -> parsers
  -> source blocks
  -> project facts
  -> conflicts
  -> wiki pages / handover / ask
```

Markdown 是输出格式，不是内部事实来源。内部真实来源是带来源支撑的内容块和事实。

## 试用预览版

安装预览包并启动本地工作区：

```bash
npm install -g whywiki
whywiki
```

这个命令会启动本地 Web 应用，并打印本地访问地址：

```text
WhyWiki is running locally.

Open:
http://127.0.0.1:8765

Logs:
whywiki log
```

打开这个地址，创建项目，导入一个本地文件夹，然后检查项目状态、冲突、Wiki 页面、交接包、来源材料，以及带证据的 Ask。

本地仓库开发时，可以使用重启脚本：

```bash
./start.sh
```

该脚本会创建或复用 `.venv`，以本地模式安装 WhyWiki，停止 `127.0.0.1:8765` 上的旧服务，初始化 SQLite 数据库，并在 <http://127.0.0.1:8765> 启动一个新的 Web 应用。

## 当前首板

首板已经是一个可运行的本地骨架：

- SQLite 元数据存储
- 本地文件导入
- 通过同一套文件遍历器导入本地 Git 仓库
- Markdown、文本、CSV、Python/源码解析器
- 如果安装了依赖，可以选择启用 PDF、DOCX 和 XLSX 解析器
- 确定性的事实提取
- 确定性的冲突检测
- Markdown Wiki 生成
- 交接包生成
- 简单的带证据问答
- FastAPI API 表面
- 本地 Web dashboard
- CLI 命令
- Dockerfile 和 docker-compose
- `docs/CODEX_TASKS.md` 中的 Codex 任务指南

仍然刻意保持浅层的部分：

- 生产级 LLM 提取
- 向量搜索
- 在线表格连接器
- GitHub/GitLab/Gitea 连接器
- 权限、SSO、审计日志、多租户
- 超出 Python 基础分析范围的高级 AST 分析
- 异步 worker 队列

## 协作模型

WhyWiki 使用 Git provider 做协作。

一个 WhyWiki 工作区会关联到 GitHub 或 Gitea 仓库。这个工作区仓库存储项目记忆产物，而不是复制它所描述的代码仓库。关联的代码仓库仍然保留在原来的 provider 中，WhyWiki 通过 provider、仓库、commit、路径和范围来引用它们。

`whywiki.db` 是本地可重建缓存，不应该提交到仓库。工作区仓库才是持久协作层，用来保存配置、事实、冲突、评审事件、Wiki 页面、交接输出，以及被固定的带证据答案。

访问权限继承自 provider：

- 拥有工作区仓库读权限的用户可以进入工作区。
- 拥有工作区仓库写权限的用户可以批准事实并解决冲突。
- 拥有关联源代码仓库读权限的用户可以查看来源证据，并基于引用的来源重建项目记忆。

### 真实 Provider 登录

WhyWiki 可以连接 GitHub 和 Gitea 账号，用于本地工作区访问检查。

- GitHub 登录使用 OAuth device flow。启动 WhyWiki 前设置 `WHYWIKI_GITHUB_CLIENT_ID`。
- Gitea 登录使用带 PKCE 的 OAuth2 Authorization Code。请在 Gitea 服务器上注册一个 public OAuth 应用，并把 `http://127.0.0.1:8765/api/auth/gitea/callback` 作为 redirect URL。
- 可用时，token 会存入操作系统凭据存储：macOS Keychain、Windows Credential Manager / DPAPI-backed storage，或 Linux Secret Service。
- `accounts.json` 只保存账号元数据，绝不保存 token。
- 在没有桌面凭据服务的 Linux 上，token 会自动存储在 `$XDG_DATA_HOME/whywiki/tokens.json`（默认 `~/.local/share/whywiki/tokens.json`），文件权限为 0600。

## 开发者设置

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
whywiki init-db
whywiki create "My Project"
whywiki ingest <PROJECT_ID> /path/to/your/project
whywiki build <PROJECT_ID>
whywiki ask <PROJECT_ID> "这个项目当前有哪些冲突？"
whywiki serve
```

打开 <http://localhost:8080>。

## Docker 设置

```bash
docker compose up --build
```

## Codex 工作流

1. 阅读 `AGENTS.md`。
2. 阅读 `docs/CODEX_TASKS.md`。
3. 当公开安装方式、行为、产品定位或功能状态变化时，同步更新 `README.md` 和 `README.zh-CN.md`。
4. 当功能行为变化时，更新 `docs/FEATURE_STATUS.md`。
5. 一次只处理一个任务。
6. 每次有意义的修改后运行：

```bash
python -m compileall whywiki
python -m pytest -q
```

## 产品方向

WhyWiki 应该像一个本地产品，而不是源码 demo。

理想流程：

```text
choose a project
  -> import materials
  -> build project memory
  -> review conflicts
  -> use the wiki, handover pack, and evidence-backed answers
```

首板优先级：

1. 让本地项目流程更稳。
2. 让公开包、命令、文档和 UI 都统一到 `whywiki`。
3. 支持 `init-db`、`create`、`ingest`、`build`、`ask` 和 `serve`。
4. 改进 blocks 和 facts。
5. 改进冲突检测。
6. 改进 Web UI。
7. 只有在确定性行为稳定后，才加入 LLM 调用。

WhyWiki 应该保持小型、本地优先、可检查，并且有证据支撑。
