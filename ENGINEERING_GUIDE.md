# Agent Team Demo — 工程师技术导读

> 面向后续基于此 demo 开发完整 Agent 框架的工程师。阅读本文后你应理解 demo 验证了什么、架构怎么工作、正式开发该怎么做。

---

## 一、这个 Demo 验证了什么

Demo 在本地 Mac 上跑通了一条完整的 **Agent 协作链路**，**三个 Agent 全部由 LLM 驱动**：

```
用户发送任务 "写一个冒泡排序"
  → Manager Agent（总控，LLM 驱动）
    → OpenViking 检索历史经验
    → LLM 任务规划：将用户任务 + 参考材料 → 精炼的开发规格
    → Coder Agent → LLM 生成代码 → 写入 Sandbox
    → Tester Agent → 在 Sandbox 执行代码 → LLM 分析执行结果 → 判定 Pass/Fail
    → 如果 Fail，LLM 分析错误根因 → 携带修复建议重试 Coder（最多 3 次）
    → 如果 Pass，归档代码到 OpenViking
  → 返回结果给用户
```

**三个核心验证点**：

| 验证点 | 结论 |
|--------|------|
| Restate 编排能力 | Agent 间 RPC（`ctx.service_call` / `ctx.object_call`）+ 状态保持（`ctx.get/set`）+ side effect 持久化（`ctx.run`）均可用 |
| OpenViking 知识流转 | "检索 → 生成 → 归档" 闭环跑通，`find` + `overview` + `add_resource` API 工作正常 |
| Sandbox 模拟 | 本地文件系统 + subprocess 模拟 Pod 执行环境可行，支持代码写入/读取/执行 |
| 三 Agent 均 LLM 驱动 | Manager（任务规划 + 错误分析）、Coder（代码生成）、Tester（结果分析）均通过 LLM 完成核心决策，体现 "Agent = LLM + 工具" 模式 |

**实测结果**：发送 "写一个冒泡排序" → LLM 规划任务 → LLM 生成代码 → 执行 → LLM 分析结果 → 一次通过，零重试。

---

## 二、技术栈

| 组件 | 选型 | 版本 | 角色 |
|------|------|------|------|
| 编排引擎 | [Restate](https://restate.dev/) | server binary | Agent 间 RPC、状态管理、side effect 持久化 |
| 知识库 | [OpenViking](https://github.com/volcengine/OpenViking) | 0.1.17 | 知识存储/检索，L0/L1/L2 分层上下文 |
| LLM | Anthropic SDK + 自定义 endpoint | — | Agent 思考能力（兼容 OpenAI 的 LLM 服务） |
| 沙箱 | 本地文件系统 + subprocess | — | 模拟代码执行环境 |
| 包管理 | [uv](https://docs.astral.sh/uv/) | — | Python 项目管理 |

---

## 三、5 分钟跑通

```bash
cd lab8_restate_viking_agents

# 1. 安装依赖
uv sync && uv sync --group dev

# 2. 配置环境变量（复制模板并填写你的 API keys）
cp .env.example .env
# 编辑 .env 填入你的 LLM 和 Embedding 服务配置

# 3. 启动 Restate server（另一个终端，如果还没启动）
restate-server

# 4. 启动应用
uv run python -m src.main        # 监听 9080

# 5. 注册服务到 Restate（另一个终端，只需执行一次）
curl localhost:9070/deployments \
  -H 'content-type: application/json' \
  -d '{"uri": "http://localhost:9080", "force": true}'

# 6. 发送任务
curl localhost:8080/manager/my_project/handle_task \
  -H 'content-type: application/json' \
  -d '{"task": "写一个冒泡排序，对列表 [5,3,1,4,2] 排序并打印结果"}'

# 7. 跑测试
uv run pytest -v                                   # 58 单元测试
uv run pytest tests/test_integration.py -v         # 8 集成测试（需要 app + restate 运行中）
```

---

## 四、架构与数据流

### 4.1 模块划分

```
src/
├── config.py              # 配置加载（.env → Config dataclass）
├── main.py                # 入口：注册 Restate 服务 + Hypercorn 启动
├── infra/                 # 基础设施层（对应设计文档的 Body World）
│   ├── llm.py             #   LLMClient: Anthropic SDK 封装
│   ├── ov_client.py       #   OVClient: OpenViking 封装
│   └── sandbox.py         #   SandboxManager: Restate Service（文件读写 + 命令执行）
└── agents/                # 智能体层（对应设计文档的 Brain World）
    ├── manager.py          #   ManagerAgent: 总控编排（Virtual Object）
    ├── coder.py            #   CoderAgent: LLM 代码生成（Virtual Object）
    └── tester.py           #   TesterAgent: 代码执行验证（Virtual Object）
```

### 4.2 Restate 服务类型

| 服务 | 类型 | 有状态 | 说明 |
|------|------|--------|------|
| `sandbox` | **Service** | 否 | 无状态的文件/命令操作，任何 handler 都可并行调用 |
| `manager` | **VirtualObject** | 是 | 按 project_id 隔离状态，同一 key 的调用串行执行 |
| `coder` | **VirtualObject** | 是 | 按 project_id 隔离，保证同一项目的代码生成不并发 |
| `tester` | **VirtualObject** | 是 | 按 project_id 隔离 |

### 4.3 端到端调用链

```
用户 HTTP POST → Restate Ingress (8080)
  → manager/{project_id}/handle_task
    ├─ ctx.service_call(sandbox.create_project, arg=project_id)
    ├─ ctx.run("ov_retrieve", _ov_retrieve)          ← side effect, 持久化
    ├─ ctx.run("llm_plan", _llm_plan)                ← LLM 任务规划
    ├─ loop (max 3):
    │   ├─ ctx.object_call(coder.generate_code, key=project_id, arg=...)
    │   │   ├─ ctx.run("llm_generate_code", _call_llm)   ← side effect
    │   │   └─ ctx.service_call(sandbox.write_file, arg=...)
    │   └─ ctx.object_call(tester.run_test, key=project_id, arg=...)
    │       ├─ ctx.service_call(sandbox.exec_command, arg=...)
    │       └─ ctx.run("llm_analyse", _llm_analyse)       ← LLM 结果分析
    │   └─ if failed: ctx.run("llm_error_analysis_{n}")   ← LLM 错误分析
    ├─ if success: ctx.service_call(sandbox.read_file) + ctx.run("ov_archive")
    └─ return {project_id, status, retries, code, test_output}
```

### 4.4 HTTP API

所有调用通过 Restate Ingress（默认 8080 端口）：

```bash
# Sandbox（Service，直接按 handler 名调用）
POST /sandbox/create_project       Body: "project_id"
POST /sandbox/write_file           Body: {"project_id", "filename", "content"}
POST /sandbox/read_file            Body: {"project_id", "filename"}
POST /sandbox/exec_command         Body: {"project_id", "command"}

# Agents（Virtual Object，URL 中带 key）
POST /manager/{key}/handle_task    Body: {"task": "..."}
POST /coder/{key}/generate_code    Body: {"task", "reference", "error_feedback"?}
POST /tester/{key}/run_test        Body: {"project_id", "filename"}
```

---

## 五、关键代码走读

### 5.1 Restate 核心模式

**Service（无状态）** — sandbox.py:
```python
from restate import Service, Context

sandbox = Service("sandbox")

@sandbox.handler()
async def create_project(ctx: Context, project_id: str) -> dict:
    async def _create():                  # 必须是 async
        os.makedirs(base, exist_ok=True)
        return {"project_id": project_id, "path": base}
    return await ctx.run("create_project", _create)  # side effect 持久化
```

**Virtual Object（有状态）** — manager.py:
```python
from restate import VirtualObject, ObjectContext

manager = VirtualObject("manager")

@manager.handler()
async def handle_task(ctx: ObjectContext, req: dict) -> dict:
    project_id = ctx.key()                              # 获取对象实例 key
    ctx.set("status", "started")                        # 写状态
    status = await ctx.get("status")                    # 读状态
    result = await ctx.service_call(fn, arg=data)       # 调用 Service
    result = await ctx.object_call(fn, key=k, arg=data) # 调用另一个 Virtual Object
    result = await ctx.run("label", async_fn)           # 执行 side effect
```

### 5.2 ctx.run() 的核心意义

`ctx.run()` 是 Restate **持久化执行**的关键。被包裹的函数：
- 首次执行时：运行函数，将结果写入 Restate journal
- 重试/恢复时：直接从 journal 读取结果，**不再执行函数**

这意味着 LLM 调用、文件 I/O、外部 API 都必须包裹在 `ctx.run()` 中，否则重试时会重复执行。

```python
# 正确：LLM 调用包裹在 ctx.run 中
response = await ctx.run("llm_call", _call_llm)

# 错误：直接调用会导致重试时重复执行
response = llm_client.chat(system, user)
```

### 5.3 OVClient 自动生成 ov.conf

OpenViking 需要 `~/.openviking/ov.conf` 配置 embedding 和 VLM 模型。`OVClient.__init__` 会自动从 `.env` 生成：

```python
def _ensure_ov_conf():
    conf = {
        "embedding": {"dense": {
            "provider": "...",
            "api_key": cfg.embedding_api_key,
            "api_base": cfg.embedding_api_base,
            "model": cfg.embedding_model,
            "dimension": cfg.embedding_dim,
        }},
        "vlm": {
            "provider": "...",
            "api_key": cfg.embedding_api_key,
            "model": cfg.vlm_model,
        }
    }
    Path("~/.openviking/ov.conf").write_text(json.dumps(conf))
```

### 5.4 Coder 的代码提取

LLM 返回 markdown 格式的代码，`_extract_code()` 按优先级提取：
1. ` ```python ... ``` ` 块（最优）
2. ` ``` ... ``` ` 通用代码块
3. 全文兜底（去掉首尾空白）

### 5.5 Tester 的 LLM 分析

Tester 使用 LLM 分析执行结果，取代原来的简单启发式规则：

```python
# LLM 分析执行结果
llm_response = await ctx.run("llm_analyse", _llm_analyse)

# 从 LLM 回复中提取 VERDICT: PASS 或 VERDICT: FAIL
verdict = _parse_verdict(llm_response)
if verdict is not None:
    passed = verdict
else:
    # Fallback 到启发式规则
    passed = _analyse_result(returncode, stdout, stderr)
```

`_parse_verdict()` 使用正则匹配 `VERDICT: PASS/FAIL`（大小写不敏感）。如果 LLM 没有返回清晰的 verdict，则 fallback 到原有的 `_analyse_result()` 启发式判断。

### 5.6 Manager 的 LLM 规划与错误分析

Manager 在两个关键环节使用 LLM：

**任务规划**（Step 3）：将用户原始任务 + OV 参考材料发给 LLM，产出精炼的开发规格。Coder 收到的是 LLM 精炼后的 `refined_task` 而非原始 `task`。

```python
refined_task = await ctx.run("llm_plan", _llm_plan)
# Coder 收到 refined_task
coder_req = {"task": refined_task, "reference": reference}
```

**错误分析**（重试循环）：当测试失败时，Manager 将原始任务 + 生成的代码 + 执行输出发给 LLM 做根因分析，Coder 收到的是 LLM 的修复建议而非原始 stderr。

```python
error_feedback = await ctx.run(f"llm_error_analysis_{attempt}", _llm_error_analysis)
# 下一轮 Coder 收到 LLM 的修复建议
coder_req["error_feedback"] = error_feedback
```

---

## 六、测试结构

```
tests/
├── test_config.py        8 tests   配置加载、默认值、frozen
├── test_sandbox.py      11 tests   文件读写、命令执行、超时
├── test_llm.py           5 tests   Anthropic SDK mock
├── test_ov_client.py    10 tests   ov.conf 生成、add/retrieve mock
├── test_coder.py         9 tests   代码提取纯函数
├── test_tester.py       15 tests   结果分析纯函数
└── test_integration.py   8 tests   通过真实 Restate server 走完整链路
                         ────────
                         66 tests
```

单元测试（58 个）全部 mock 外部依赖，秒级完成。
集成测试（8 个）需要 Restate server + app 运行，约 30 秒（含 LLM 调用）。

---

## 七、Demo 的局限性（正式开发必须解决）

### 7.1 Sandbox 是 /tmp 目录 + subprocess

当前用本地文件系统模拟 Pod：
- 无隔离：所有项目共享同一机器，恶意代码可访问整个文件系统
- 无资源限制：没有 CPU/内存/磁盘配额
- 无并发控制：同一 project_id 下的多个 exec 可能冲突

**正式方案**：替换为容器化沙箱（Docker / Kubernetes Pod / Firecracker），通过 API 管理生命周期。

### 7.2 LLM 调用没有 streaming

当前 `LLMClient.chat()` 是同步阻塞调用，等待完整响应。LLM 生成代码可能需要 10-30 秒。

**正式方案**：
- 支持 streaming（`client.messages.stream()`）
- 给用户实时反馈进度
- 或使用 Restate 的 `ctx.awakeable()` + webhook 做异步回调

### 7.3 Manager 的重试逻辑仍可增强

Manager 已具备 LLM 驱动的错误分析能力（根因分析 + 修复建议），但仍缺少：
- 错误分类后的不同处理策略（语法错误 vs 逻辑错误 vs 依赖缺失 → 不同修复路径）
- 复杂任务的分解/拆解能力

### 7.4 Agent 只有一种固定工具

Coder 只能 "生成一个 main.py"。正式版需要：
- 多文件生成能力
- 依赖安装（pip install）
- 文件修改/追加（而非只有全量写入）
- 更多工具：搜索文档、读取已有代码、运行测试套件

### 7.5 OpenViking 知识归档是粗粒度的

当前直接把整个代码文件归档为一个 resource。没有：
- 结构化的经验提取（"这个任务用了什么算法"、"踩了什么坑"）
- 按任务类型分类索引
- 知识的版本管理和去重

### 7.6 配置硬编码较多

- Sandbox 路径硬编码 `/tmp/lbg`
- Coder 只生成 `main.py`
- LLM system prompt 写死在代码里
- 重试次数固定 3 次

### 7.7 缺少可观测性

日志有了，但缺少：
- 结构化 tracing（每个任务的完整调用链）
- Metrics（LLM 调用延迟、成功率、重试率）
- Restate admin dashboard 集成

---

## 八、正式开发建议

### 8.1 推荐的开发顺序

```
Phase 1: Sandbox 容器化
  → Docker/K8s Pod 替换 /tmp + subprocess
  → 文件系统隔离 + 资源限制 + 生命周期管理

Phase 2: Agent 能力增强
  → Coder 支持多文件、依赖安装、代码修改
  → Tester 支持 pytest 运行、覆盖率检测
  → Manager 支持任务分解、错误分类、动态策略

Phase 3: 知识系统完善
  → 结构化经验提取和索引
  → 任务模板匹配
  → 知识的版本和生命周期管理

Phase 4: 生产化
  → LLM streaming + 异步回调
  → 可观测性（tracing, metrics, alerting）
  → 多用户/多租户
  → 权限控制和审计
```

### 8.2 Restate SDK 开发备忘

```python
# ── Import ────────────────────────────────────────
from restate import Service, Context                       # 无状态服务
from restate import VirtualObject, ObjectContext            # 有状态对象
from restate import Workflow, WorkflowContext               # 工作流（只运行一次）

# ── 定义服务 ──────────────────────────────────────
svc = Service("name")                                      # 无状态
obj = VirtualObject("name")                                # 有状态，按 key 隔离
wf  = Workflow("name")                                     # 有状态，只运行一次

# ── Handler ───────────────────────────────────────
@svc.handler()
async def my_handler(ctx: Context, arg: str) -> dict: ...

@obj.handler()                                             # 默认 exclusive
async def my_handler(ctx: ObjectContext, arg: dict) -> dict:
    key = ctx.key()                                        # 获取 key

@obj.handler(kind="shared")                                # 并发只读
async def get_status(ctx: ObjectSharedContext) -> dict: ...

# ── RPC ───────────────────────────────────────────
await ctx.service_call(handler_fn, arg=data)               # 调用 Service
await ctx.object_call(handler_fn, key=k, arg=data)         # 调用 Virtual Object
ctx.service_send(handler_fn, arg=data)                     # fire-and-forget
ctx.object_send(handler_fn, key=k, arg=data)               # fire-and-forget

# ── Side Effect ───────────────────────────────────
result = await ctx.run("label", async_fn)                  # 持久化执行

# ── State ─────────────────────────────────────────
val = await ctx.get("key")                                 # 读（返回 None 或 value）
ctx.set("key", value)                                      # 写
ctx.clear("key")                                           # 删
ctx.clear_all()                                            # 清空

# ── 注册 + 启动 ──────────────────────────────────
app = restate.app(services=[svc, obj, wf])                 # 创建 ASGI app
# 用 Hypercorn 启动，然后 curl Restate admin 注册
```

### 8.3 OpenViking API 备忘

```python
import openviking as ov

client = ov.SyncOpenViking(path="./data")
client.initialize()

# 添加知识
result = client.add_resource(path="./file.py", target="viking://resources/code/")
client.wait_processed()

# 搜索
results = client.find("sorting algorithm", limit=5)
for r in results.resources:
    print(r.uri, r.score)

# 分层上下文
client.abstract(uri)    # L0: 一句话摘要 (~100 tokens)
client.overview(uri)    # L1: 核心信息 (~2K tokens)
client.read(uri)        # L2: 完整原文

# 目录操作
client.ls(uri)
client.glob(pattern="**/*.py", uri=root_uri)

client.close()
```

配置文件 `~/.openviking/ov.conf`（由 OVClient 自动从 .env 生成）：
```json
{
  "embedding": {
    "dense": {
      "provider": "your-provider",
      "api_key": "...",
      "api_base": "https://api.your-embedding-provider.com/v3",
      "model": "your-embedding-model",
      "dimension": 2048
    }
  },
  "vlm": {
    "provider": "your-provider",
    "api_key": "...",
    "api_base": "https://api.your-embedding-provider.com/v3",
    "model": "your-vlm-model"
  }
}
```

### 8.4 值得复用的部分

| 模块 | 可复用性 | 说明 |
|------|---------|------|
| `sandbox.py` | **高** | Restate Service 模式可直接复用，替换底层为容器 API 即可 |
| `manager.py` | **高** | 编排模式（创建 → 检索 → 生成 → 测试 → 重试 → 归档）是通用模板 |
| `coder.py` | **中** | 代码提取逻辑可复用，但 LLM 调用方式需要扩展（多轮、streaming） |
| `tester.py` | **中** | 判定逻辑过于简单，但 Restate Virtual Object 模式可复用 |
| `ov_client.py` | **中** | OpenViking 封装可复用，但 ov.conf 生成逻辑建议改为显式配置 |
| `config.py` | **低** | 正式版应使用更完善的配置管理（如 pydantic-settings） |

---

## 九、文件清单

```
lab8_restate_viking_agents/
├── .env                     API keys 和端点配置（不入 git）
├── .env.example             配置模板（无真实密钥，入 git）
├── .gitignore               排除 .env, .venv, data/, /tmp/lbg/
├── design.md                原始设计文档
├── ENGINEERING_GUIDE.md     本文档
├── pyproject.toml           uv 项目配置
├── src/
│   ├── config.py            配置加载              35 行
│   ├── main.py              入口 + Hypercorn      37 行
│   ├── infra/
│   │   ├── llm.py           LLM 封装              34 行
│   │   ├── ov_client.py     OpenViking 封装       104 行
│   │   └── sandbox.py       Sandbox Restate Svc    89 行
│   └── agents/
│       ├── manager.py       总控编排              133 行
│       ├── coder.py         代码生成               85 行
│       └── tester.py        执行验证               70 行
└── tests/
    ├── test_config.py        8 tests
    ├── test_sandbox.py      11 tests
    ├── test_llm.py           5 tests
    ├── test_ov_client.py    10 tests
    ├── test_coder.py         9 tests
    ├── test_tester.py       15 tests
    └── test_integration.py   8 tests (需要 Restate + app)
                             66 tests total
```

---

## 十、启动顺序与端口

```
Restate Server       →  admin: 9070, ingress: 8080
App (Hypercorn)      →  9080 (Restate 通过此端口调用 handler)
```

启动顺序：
1. `restate-server`（或确认已在运行）
2. `uv run python -m src.main`（启动 app）
3. `curl localhost:9070/deployments -H 'content-type: application/json' -d '{"uri": "http://localhost:9080", "force": true}'`（注册服务，每次 app 代码变更后需重新注册）
4. 通过 `curl localhost:8080/...` 发请求

**注意**：代码改动后需要重启 app 并重新注册到 Restate（带 `"force": true`），否则 Restate 仍调用旧的 handler。
