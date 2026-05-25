# WhyWiki 功能状态台账

最后更新：2026-05-26

这份文档用于长期维护 WhyWiki 的功能状态。每次新增、删除或改变功能行为时，都应同步更新这里。

状态说明：

- 已完成：已有实现，并且有测试、本地验证或可复现命令验证。
- 部分完成：首板可用，但能力深度或用户界面还不完整。
- 计划中：适合作为近期首板迭代。
- 暂缓：第一版明确不做，避免产品跑偏。

## 产品闭环

WhyWiki 首板的核心闭环是：

```text
选择项目
  -> 导入资料
  -> 生成带证据的项目知识
  -> 审查需求冲突
  -> 使用 Wiki、交接包和带证据问答
```

## 功能矩阵

| 模块 | 功能 | 状态 | 依据 / 备注 |
| --- | --- | --- | --- |
| 启动 | `./start.sh` 本地开发启动脚本 | 已完成 | 创建或复用 `.venv`，安装 editable package，初始化数据库，启动 `127.0.0.1:8765`。见 `start.sh` 和 `tests/test_start_script.py`。 |
| 启动 | npm package launcher | 已完成 | `package.json` 把 `whywiki` 映射到 `npm/whywiki.js`；公开路径是 `npm install -g whywiki` 后运行 `whywiki`。 |
| 启动 | 固定默认本地地址 | 已完成 | 默认产品地址是 `http://127.0.0.1:8765`；不应静默 fallback 到随机端口。见 `whywiki/runtime.py`、`whywiki/cli.py`、`tests/test_runtime_cli.py`。 |
| 启动 | 运行状态、日志、诊断、打开地址 | 部分完成 | `status`、`log`、`doctor`、`open` 已存在；`stop` 目前仍是占位，只提示前台服务用 `Ctrl+C` 停止。 |
| 项目 | 初始化数据库 | 已完成 | `whywiki init-db`，底层在 `whywiki/db.py`。 |
| 项目 | 创建和列出项目 | 已完成 | `whywiki create`、`whywiki list`、`POST /api/projects`、`GET /api/projects`；Web/API 项目记录支持多标签，用于首页筛选。 |
| 摄入 | 本地文件夹摄入 | 已完成 | `whywiki ingest <PROJECT_ID> <path>` 和 `POST /api/projects/{project_id}/ingest`；实现位于 `whywiki/services/ingest.py`。 |
| 摄入 | Git 仓库摄入 | 部分完成 | `--source-type git` 已接受，但首板仍复用本地文件 walker，还没有 Git 历史/提交语义分析。 |
| 摄入 | 忽略无关目录 | 已完成 | 忽略 `.git`、`.venv`、`node_modules`、构建产物、缓存和 `.whywiki`。 |
| Parser | Markdown 按标题分块 | 已完成 | 见 `whywiki/parsers/markdown.py`。 |
| Parser | 普通文本解析 | 已完成 | 见 `whywiki/parsers/plaintext.py`。 |
| Parser | CSV 解析 | 已完成 | 见 `whywiki/parsers/csv_parser.py`。 |
| Parser | Python/source code 解析 | 部分完成 | 能抽取基础 Python 结构和 API 线索；高级 AST 和 tree-sitter 暂未做。 |
| Parser | PDF 解析 | 部分完成 | optional parser 已存在，依赖可用时保留 page-oriented evidence。 |
| Parser | DOCX 解析 | 部分完成 | optional parser 已存在，尽量保留段落/表格类 evidence。 |
| Parser | XLSX 解析 | 部分完成 | optional parser 已存在，尽量保留 sheet/row 类 evidence。 |
| Facts | 确定性事实抽取 | 已完成 | `whywiki/services/fact_extractor.py` 会抽取首板事实并保留 evidence pointer。 |
| Facts | 事实类型 | 部分完成 | 已覆盖 requirement/api/code/experiment/deployment/document 风格事实；decision 抽取仍较浅。 |
| Facts | 需求生命周期 | 已完成 | `fact_type=requirement` 支持当前有效、待确认、已被替代、已拒绝、历史参考等语义；内部枚举保留英文，用户界面通过 i18n 显示本地化状态。 |
| Facts | 人工确认事实 | 已完成 | `PATCH /api/projects/{project_id}/facts/{fact_id}` 会持久化 `candidate`、`confirmed`、`needs_review` 状态；Web UI 的“确认这个事实”使用该 API。 |
| Facts | LLM-assisted extraction | 计划中 | 等 deterministic behavior 稳定后再加，不能成为基础流程必需条件。 |
| 冲突 | 多份 latest/final 文档 | 已完成 | 检测多个材料同时声称 `latest/final/最新版/最终版`。 |
| 冲突 | API endpoint 不一致 | 已完成 | 检测类似 `/api/user/create` vs `/api/users/create` 的路径不一致。 |
| 冲突 | 文档提到的文件缺失 | 已完成 | 检测材料提到但未在摄入来源中找到的脚本或配置文件。 |
| 冲突 | 模型/部署漂移 | 已完成 | 检测 LSTM vs Transformer、v1 vs v2 等模型架构或版本漂移。 |
| 冲突 | 稳定 conflict key 和审查状态保留 | 已完成 | rebuild 后仍保留相同冲突的 review status。 |
| 冲突 | 冲突状态更新 API | 已完成 | `PATCH /api/projects/{project_id}/conflicts/{conflict_id}` 支持 `open`、`resolved`、`ignored`。 |
| 冲突 | 需求冲突裁决记录 | 已完成 | 冲突解决会写入 `requirement_decisions`，胜出需求进入当前需求集，被淘汰需求保留为已被替代或历史参考。 |
| 冲突 | 冲突审查 UI 操作 | 已完成 | Web UI 的冲突卡支持直接 resolve/ignore，并复用 `PATCH /api/projects/{project_id}/conflicts/{conflict_id}`。 |
| Wiki | Markdown Wiki 生成 | 已完成 | `whywiki build` 会生成 overview、requirements、architecture、api、experiments、deployment、conflicts、handover、open-questions 页面。 |
| Wiki | 当前需求快照 | 已完成 | requirements Wiki 页面从结构化当前需求集生成，展示当前有效需求、已被替代需求、未解决冲突和证据。 |
| Wiki | 带证据的 Wiki 内容 | 部分完成 | 页面里有 evidence pointer，但页面质量、不确定性表达和信息组织仍是首板水平。 |
| Wiki | 人工编辑区域保留 | 计划中 | 后续应保留人工编辑区域，避免生成时整体覆盖。 |
| 交接包 | Handover pack 生成 | 已完成 | build 会生成 handover 页面，并通过 `GET /api/projects/{project_id}/handover` 暴露。 |
| Ask | 带证据问答 | 已完成 | `whywiki ask` 和 `POST /api/projects/{project_id}/ask` 只基于已摄入 facts/blocks 回答。 |
| Ask | 无证据问题拒答 | 已完成 | 缺少证据的问题会返回 no-evidence response。见 `tests/test_evidence_outputs.py`。 |
| Ask | 冲突类问题回答 | 已完成 | 例如 `这个项目当前有哪些冲突？` 会直接返回 open conflicts 和 evidence。 |
| Ask | 生产级 RAG / vector search | 暂缓 | 不属于首板目标。 |
| Web UI | 本地 dashboard shell | 已完成 | 静态页面由 FastAPI 提供，文件在 `whywiki/static/index.html`、`styles.css`、`app.js`、`i18n.js`。 |
| Web UI | 项目首页与项目内导航 | 已完成 | 默认进入项目列表首页；左侧需求现状、原始文件、需求冲突点、需求问答等工作区导航只在打开具体项目后显示。见 `whywiki/static/index.html`、`whywiki/static/app.js` 和 `tests/test_web_assets.py`。 |
| Web UI | 项目标签筛选 | 已完成 | 项目首页展示项目标签 chips，支持多选筛选、空标签提示、无匹配清除筛选；项目创建和卡片菜单均可维护标签。 |
| Web UI | 项目删除入口 | 已完成 | 项目卡片右上角三点菜单提供“删除”危险操作，删除前二次确认；删除当前项目会清空当前项目状态并刷新项目列表。 |
| Web UI | 需求现状视图 | 已完成 | 展示 source/fact/conflict/wiki 指标和当前待审查摘要，并提供项目内摄入和生成入口。 |
| Web UI | 原始文件视图 | 已完成 | 能列出来源，并通过 API 查看 source/block 内容。 |
| Web UI | 需求冲突点视图 | 已完成 | 能展示 conflicts 和 review facts，并提供 resolve/ignore 操作入口。 |
| Web UI | Wiki index | 已完成 | Wiki 索引在 topbar，不作为日常首页。 |
| Web UI | 需求问答视图 | 已完成 | 有默认问题，渲染 answer 和 structured evidence。 |
| Web UI | Settings / handover export | 部分完成 | Settings 能展示 handover；更完整的导出/下载体验未做。 |
| Web UI | 中英文切换 | 已完成 | 有中文/英文 language switch，并由 web asset tests 覆盖。 |
| Web UI | 生命周期本地化状态 | 已完成 | 中文模式显示“当前有效 / 已被替代 / 待确认”等中文状态；英文模式显示对应英文状态，不在主 UI 暴露裸枚举。 |
| Git provider login | 真实 Provider 登录 | 已完成 | GitHub device flow 和 Gitea PKCE 可在本地连接 provider 账号；token 不进入 `accounts.json`，默认走系统凭据存储，开发环境可显式启用文件 fallback。 |
| Web UI | 证据原文查看 | 已完成 | `GET /api/projects/{project_id}/facts/{fact_id}/evidence` 和 `/conflicts/{conflict_id}/evidence` 会解析 evidence pointer，返回原始 block 片段、来源、路径和位置；Web 证据抽屉可加载原文。 |
| Web UI | 扫描/生成进度 | 已完成 | Web 扫描和生成 Wiki 走 `ingest-jobs`、`build-jobs` 与 `/api/jobs/{job_id}` 轮询，状态持久化在 `operation_jobs`。 |
| API | Project API | 已完成 | create/list/get/update-tags/delete project endpoints 已存在；删除项目会级联清理来源、blocks、facts、conflicts、wiki pages 和 operation jobs。 |
| API | Source/block/fact API | 已完成 | endpoints 已暴露 sources、source blocks、facts。 |
| API | Wiki/conflict/handover/ask API | 已完成 | endpoints 已暴露 wiki pages、conflicts、conflict status update、handover、ask。 |
| 测试 | 混乱项目测试夹具 | 已完成 | `tests/fixtures/messy-project` 仅作为测试/开发夹具使用，不作为产品内置 Demo 入口或 packaged asset。 |
| 测试 | 核心单测和 API 测试 | 已完成 | 当前测试覆盖 parser、摄入/构建、runtime CLI、web assets、conflict detection、evidence outputs、API surface。 |

## Git Provider Collaboration

Status: real provider login and token-backed workspace checks implemented for
local GitHub and Gitea accounts.

Implemented surface:

- workspace artifact schema
- local connected-account metadata
- GitHub OAuth device-flow login
- Gitea OAuth2 Authorization Code with PKCE login
- OS credential token storage with explicit development file fallback
- provider permission abstraction
- workspace read/write access reports
- linked repo access reports
- collaboration API and CLI status surfaces

Not included in this slice:

- source repo write actions
- pull request creation
- hosted storage
- enterprise role management

## 第一版暂缓范围

这些能力第一版明确不做：

- 泛化 RAG chatbot。
- 默认向量搜索问答引擎。
- GitHub/GitLab/Gitea 替代能力。
- Notion/Confluence/Feishu 替代能力。
- 企业权限、SSO、审计日志、多租户。
- 生产级异步 worker queue 和部署编排。首板仅保留本地 SQLite `operation_jobs` 进度状态。
- 图谱可视化作为主产品形态。

## 完成定义

一项功能只有同时满足下面条件，才能在本台账中标记为“已完成”：

1. 有明确用户入口，例如 CLI 命令、Web 操作、API endpoint 或自动流程。
2. 使用真实数据路径，而不是只服务于 mock、fixture 或一次性 demo。
3. 用户可见结论保留 evidence pointer；没有证据时明确降级为未知、待确认或待审查。
4. 失败状态从产品角度设计过：应该提示用户修正、清晰报错，还是有限 fallback，不能靠静默 fallback 掩盖问题。
5. 新实现替换旧实现时，旧路径已删除、迁移或明确标注为兼容路径；不能新旧代码并存制造歧义。
6. 有聚焦测试、本地验证或可复现命令覆盖关键用户承诺。
7. README、功能台账、产品路径和相关设计文档没有与实际行为分叉。
8. 没有为了边缘场景引入不必要的重依赖、全局状态或企业化抽象。
9. 面向用户的状态、动作和错误提示必须遵守当前语言；内部枚举不能直接暴露到主 UI 或生成输出。

## 维护规则

更新这份文档时：

1. 优先用真实文件、API endpoint、测试或本地验证行为作为依据。
2. 状态要保守；功能能跑但用户流程不完整时，标为“部分完成”。
3. 只有本地验证或聚焦测试通过后，才把功能移动到“已完成”。
4. 首板叙事始终围绕项目知识闭环：选择项目、导入资料、生成带证据的知识、审查需求冲突、使用带证据的成果。
5. 记录功能状态时也要记录产品级取舍；不要把“靠隐式 fallback 勉强跑通”当成已完成。
