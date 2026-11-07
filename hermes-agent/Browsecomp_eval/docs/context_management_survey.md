# 主流 Agent 框架的上下文管理实现调研

调研对象：**Claude Code**（Anthropic 官方 CLI，闭源 minified）、**Hermes Agent**、**OpenCode**（sst/opencode，主流开源 Claude Code 替代品）、**OpenAI Codex CLI**（openai/codex，Rust 实现）、**DeerFlow**（bytedance/deer-flow，LangGraph 路线）。还有 openclaw

每节给出：核心机制 → 关键源码片段（Codex / DeerFlow / OpenCode / Hermes 来自仓库直读，Claude Code 来自官方文档 + 社区逆向）→ 评价。文末有横向对比表与选型建议。

---

## 1. Claude Code (Anthropic, 闭源)

### 1.1 整体架构

Claude Code CLI 是 minified JavaScript，没有可读源码。已知信息来自三处：

- 官方文档：`docs.claude.com/en/docs/claude-code/memory` 和 `platform.claude.com/docs/en/build-with-claude/compaction`
- 社区分析：Hyperdev、MindStudio、Reddit r/ClaudeAI 等多篇深度文章
- 间接证据：GitHub Copilot CLI issue #3026 列出 Claude Code 对外暴露的环境变量

### 1.2 上下文管理由三层组成

**Layer 1 — Persistent memory (sessions 之间)**

- `CLAUDE.md` 文件（用户写）：项目级、用户级、组织级、`.claude/rules/*.md` 路径范围匹配
- `MEMORY.md` 文件（Claude 写）：`~/.claude/projects/<project>/memory/`，每次 session 首 200 行/25KB 自动加载
- 加载时机：session 启动；`/compact` 不会清除（"Project-root CLAUDE.md survives `/compact`"）

**Layer 2 — Auto-compact (session 内自动压缩)**

- 触发阈值：默认 **~75% 上下文窗口**（社区观测，曾经是 90%+，2025 年 Q3 调低）
- 可调：环境变量 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=60`（设置在 `~/.claude/settings.json` 的 `env` 字段）
- 行为：达到阈值后**自动总结历史**，保留关键决策与状态，释放 token；同时给用户提示 "Context left until auto-compact: 0%"
- 用户可以 `/compact` 手动触发

**Layer 3 — Server-side compaction (API 服务端，beta)**

- 这是 Claude API 自带能力，要 beta header `compact-2026-01-12`
- 客户端 `context_management.edits` 配置 `compact_20260112` strategy
- API 在快达上下文窗口时**自己**生成 `compaction` block；客户端下一次请求带回 → API 丢弃 compaction block 之前的全部内容
- 默认 trigger 150,000 tokens（最低 50,000），可自定义 `instructions` 替换总结 prompt

**Layer 4 — Context editing (2025-09 上线)**

社区分析提到："Automatically clears stale tool calls while preserving conversation flow"。意思是 tool call 结果会被自动剔除（类似 AgentHarness/Hermes 的 sliding window），但保留 assistant reasoning chain。Anthropic 没公开实现细节。

### 1.3 源码（无法直读，引自 Anthropic 官方 compaction 文档）

服务端 compaction API 使用方式：

```python
response = client.messages.create(
    model="claude-fable-5",
    max_tokens=4096,
    messages=messages,
    extra_headers={"anthropic-beta": "compact-2026-01-12"},
    extra_body={
        "context_management": {
            "edits": [{
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": 100000},
                "pause_after_compaction": True,
                "instructions": "Summarize but do not call tools..."
            }]
        }
    }
)
# 响应里出现 compaction block；客户端把它 append 回 messages，
# 下次请求 API 自动丢弃 compaction block 之前的全部内容。
```

### 1.4 设计评价

- ✅ **多层防御**：长期 memory（CLAUDE.md）+ session 内 auto-compact + tool 输出清理 + API 服务端兜底；任何一层失效都还有别的层挡住
- ✅ **从 90% 降到 75% 是关键升级**：留 25% 工作内存给 reasoning，性能反而提升（Hyperdev 报告 39% perf gain + 84% token reduction in 100-turn evals）
- ✅ **服务端 compaction 是最优雅的设计**：把上下文管理沉到 API 层，所有客户端（CLI、SDK、第三方 wrapper）共享一份实现
- ❌ 闭源黑盒，社区只能通过环境变量、`/compact` 行为反推阈值
- ❌ 服务端 compaction 还是 beta，要 opt-in，多数客户端没启用

---

## 2. Hermes Agent (本仓库)

### 2.1 整体架构

Hermes 用**插件化的 `ContextEngine` ABC**：每个 session 只激活一个 engine，由 `context.engine` 配置项决定。内置 4 个 engine（在 `plugins/context_engine/`）：

| Engine | 策略 | 源码 |
|---|---|---|
| `sliding_window` | 保留最近 N tool 结果原样，老的 tool 内容替换为 `"[tool response omitted]"` | `sliding_window/__init__.py` |
| `discard` | 删除前 N 轮（按比例 + `keep_rounds` 地板），保留 system + 第一个 user | `discard/__init__.py` |
| `summarize` | 真 LLM 总结，4 phase（prune → 找边界 → 总结 → 装配）| `summarize/__init__.py` |
| `visual` | 把历史渲染成 PDF → PNG 喂给 VLM，far history 下采样，recent 全分辨率 | `visual/__init__.py` + `visual/render.py` |

### 2.2 核心 ABC

```python
# agent/context_engine.py
class ContextEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    threshold_tokens: int = 0
    context_length: int = 0
    compression_count: int = 0
    threshold_percent: float = 0.75
    protect_first_n: int = 3       # 头部保留几条非 system 消息
    protect_last_n: int = 6

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """每次 LLM 响应后被宿主调用，更新 token 计数"""

    @abstractmethod
    def should_compress(self, prompt_tokens: int = None) -> bool:
        """是否该压缩；宿主每轮问"""

    @abstractmethod
    def compress(self, messages: List[Dict[str, Any]],
                 current_tokens: int = None,
                 focus_topic: str = None) -> List[Dict[str, Any]]:
        """实际压缩，输入 messages，返回新 messages"""
```

### 2.3 sliding_window engine（最简单，参考 AgentHarness 风格）

```python
# plugins/context_engine/sliding_window/__init__.py
class SlidingWindowEngine(ContextEngine):
    def __init__(self) -> None:
        ...
        self._window_size = 5

    def should_compress(self, prompt_tokens=None) -> bool:
        return (prompt_tokens or self.last_prompt_tokens) >= self.threshold_tokens

    def compress(self, messages, current_tokens=None, focus_topic=None):
        head_end = self._protect_head_size(messages)
        tool_indices = [i for i, m in enumerate(messages)
                        if m.get("role") == "tool" and i >= head_end]

        if len(tool_indices) <= self._window_size:
            return messages

        to_blank = set(tool_indices[:-self._window_size])
        return [
            {**msg, "content": "[tool response omitted]"} if i in to_blank else msg
            for i, msg in enumerate(messages)
        ]
```

### 2.4 visual engine（独家）

最有特色的一个：

```python
# plugins/context_engine/visual/render.py（节选）
def render_visual_compression(messages, head_end, ...):
    # 1. 把 messages 按 round 切：keep_rounds 个 round 保留在 text 形式（tail）
    # 2. 渲染区内：recent_rounds 个 round 进 recent，更早的进 history
    # 3. 两段都走 reportlab → PDF → PNG，URL 蓝色下划线 + role chip 高亮
    # 4. history 段 PIL.resize(0.75) 下采样到 ~56% 像素
    # 5. recent_pdf + history_pdf 用 PyPDF2 拼成 compact_<N>.pdf
    # 6. 装配成 multimodal user message:
    #    [text VISUAL_CONTEXT_PROMPT,
    #     text "[Older history — lower resolution]", image(detail=low),
    #     text "[Recent context — full resolution]", image(detail=high)]
```

宿主 (`agent/context_compressor.py`, 2426 行) 负责：
- 每轮调用 engine 的 `update_from_response`、`should_compress`
- 触发后 `messages = engine.compress(messages)` 并把结果写回 session DB
- 维护 `compression_count`、prompt cache breakpoint 等

### 2.5 设计评价

- ✅ **engine 完全可插拔**：换一行 `context.engine: visual` 就切策略，对比 DeerFlow 那种把上下文逻辑分散到 6 个 middleware 的方式更清晰
- ✅ **strategy_config 风格**：每个 engine 自带 `configure(strategy_config)`，参数在 yaml 里
- ✅ **支持视觉压缩**：唯一一家把 trajectory 渲染成 PNG 喂 VLM 的实现，针对 reasoning model 上下文爆炸的场景
- ❌ **没有 "force final answer" 兜底**：所有 engine 假设压缩后能继续，不像 DeepTraceHub 那样有"压不下就退出收尾"的最终防线
- ❌ **`should_compress` 用 `last_prompt_tokens`** 是滞后信号（上轮的 token 数）；OpenCode 在请求前估算 + 服务端 compaction 都更精确
- ⚠ **discard engine 是真删消息**：会破 prompt cache（不像 sliding_window 用占位符替换）。给老用户的退化路径有点危险

---

## 3. OpenCode (sst/opencode, TypeScript)

### 3.1 整体架构

文件位于 `packages/opencode/src/session/`：

| 文件 | 职责 | 行数 |
|---|---|---|
| `overflow.ts` | 阈值判断 / 可用预算计算 | 34 |
| `compaction.ts` | session 级压缩主流程：选 tail / prune 老 tool 输出 / 生成 summary | 575 |
| `summary.ts` | summary 消息构造 | 169 |
| `context-epoch.ts` (core) | "context epoch" — 系统上下文（CLAUDE.md / 时间戳等）的版本化基线 | 174 |
| `compaction.ts` (core) | 共享层：summary prompt 模板 + token 估算 | 246 |

OpenCode 的设计**最讲究**，体现在以下几个层面：

### 3.2 overflow 判断（请求发出前估算，不是事后）

```typescript
// packages/opencode/src/session/overflow.ts
const COMPACTION_BUFFER = 20_000

export function usable(input: { cfg, model, outputTokenMax }) {
  const context = input.model.limit.context
  if (context === 0) return 0

  const reserved = input.cfg.compaction?.reserved
    ?? Math.min(COMPACTION_BUFFER,
                ProviderTransform.maxOutputTokens(input.model, input.outputTokenMax))

  return input.model.limit.input
    ? Math.max(0, input.model.limit.input - reserved)
    : Math.max(0, context - ProviderTransform.maxOutputTokens(...))
}

export function isOverflow(input: { cfg, tokens, model, outputTokenMax }) {
  if (input.cfg.compaction?.auto === false) return false
  if (input.model.limit.context === 0) return false

  const count = input.tokens.total
    || input.tokens.input + input.tokens.output
       + input.tokens.cache.read + input.tokens.cache.write
  return count >= usable(input)
}
```

**关键点**：reserve 一段 buffer（默认 20k）给生成。`usable = input_limit - reserved`，超过 usable 就触发。这是 Anthropic compaction API 同款思路（trigger 默认 150k for 200k window）。

### 3.3 多种保护参数（compaction.ts 头部）

```typescript
export const PRUNE_MINIMUM = 20_000        // 至少要释放 20k token 才值得 prune
export const PRUNE_PROTECT = 40_000        // 最近 40k token 内的 tool 输出不动
const TOOL_OUTPUT_MAX_CHARS = 2_000        // summarize 时每个 tool 输出最多 2000 字符
const PRUNE_PROTECTED_TOOLS = ["skill"]    // skill 工具的输出永远保留
const DEFAULT_TAIL_TURNS = 2               // tail 默认保留 2 轮
const MIN_PRESERVE_RECENT_TOKENS = 2_000
const MAX_PRESERVE_RECENT_TOKENS = 8_000
```

### 3.4 Summarize prompt 模板（最讲究的一份）

```text
Output exactly the Markdown structure shown inside <template> and keep the
section order unchanged. Do not include the <template> tags in your response.
<template>
## Goal
- [single-sentence task summary]

## Constraints & Preferences
- [user constraints, preferences, specs, or "(none)"]

## Progress
### Done
- [completed work or "(none)"]
### In Progress
- [current work or "(none)"]
### Blocked
- [blockers or "(none)"]

## Key Decisions
- [decision and why, or "(none)"]

## Next Steps
- [ordered next actions or "(none)"]

## Critical Context
- [important technical facts, errors, open questions, or "(none)"]

## Relevant Files
- [file or directory path: why it matters, or "(none)"]
</template>

Rules:
- Keep every section, even when empty.
- Use terse bullets, not prose paragraphs.
- Preserve exact file paths, commands, error strings, and identifiers when known.
- Do not mention the summary process or that context was compacted.
```

8 个 section，模板硬约束 → 输出可被代码解析（每个 section 是 markdown heading）。

### 3.5 Prune 步骤（先做轻量清理再做 summarize）

```typescript
// packages/opencode/src/session/compaction.ts:243
const prune = Effect.fn(...)(function* (input: { sessionID: SessionID }) {
    const cfg = yield* config.get()
    if (!cfg.compaction?.prune) return
    // goes backwards through parts until there are PRUNE_PROTECT tokens worth
    // of tool calls, then erases output of older tool calls to free context space
    let total = 0, pruned = 0
    const toPrune: SessionV1.ToolPart[] = []
    let turns = 0

    loop: for (let msgIndex = msgs.length - 1; msgIndex >= 0; msgIndex--) {
      const msg = msgs[msgIndex]
      if (msg.info.role === "user") turns++
      if (turns < 2) continue   // 至少保留 2 轮
      if (msg.info.role === "assistant" && msg.info.summary) break loop
      for (let partIndex = msg.parts.length - 1; partIndex >= 0; partIndex--) {
        const part = msg.parts[partIndex]
        if (part.type !== "tool") continue
        if (part.state.status !== "completed") continue
        if (PRUNE_PROTECTED_TOOLS.includes(part.tool)) continue
        if (part.state.time.compacted) break loop
        const estimate = Token.estimate(part.state.output)
        total += estimate
        if (total <= PRUNE_PROTECT) continue   // 最近 40k token 内的不动
        pruned += estimate
        toPrune.push(part)
      }
    }
    if (pruned > PRUNE_MINIMUM) {
      // 真去删 tool 输出
      ...
    }
})
```

### 3.6 Context epoch（system prompt 的版本化基线）

`context-epoch.ts` 维护 system prompt 的"代际"：CLAUDE.md 更新、时间戳变化、cwd 改变都会生成新 baseline。Snapshot 存 SQLite。这避免了 system prompt 任意变动破坏 prompt cache。

### 3.7 设计评价

- ✅ **请求前估算 overflow**：用 `tokens.cache.read + cache.write + input + output` 累计，比 hermes 的 `last_prompt_tokens` 准
- ✅ **Prune + Summarize 两阶段**：先轻量删旧 tool 输出，效果不够再 LLM summarize；类似 hermes summarize engine 的 Phase 1，但更激进
- ✅ **超精心 summary 模板**：8 section markdown，模型很难写偏；可以代码解析
- ✅ **`PRUNE_PROTECTED_TOOLS = ["skill"]`**：skill 工具的输出永远不删 — 这是个聪明的产品选择，skill 输出通常承载关键决策
- ✅ **Context epoch 版本化 system prompt**：业界少见，避免 system prompt 漂移
- ⚠ **没有 placeholder 替换风格**（像 sliding_window）：要么完整保留 tool 输出要么彻底删；可能丢掉中等价值的中间结果
- ⚠ **代码用 Effect-TS**：阅读门槛比纯 TS 高一档

---

## 4. OpenAI Codex CLI (openai/codex, Rust)

### 4.1 整体架构

Codex CLI 的上下文管理比 OpenCode 更像“本地 client + OpenAI 服务端协作”的混合体。核心代码在 `codex-rs/core/src/` 与 `codex-rs/codex-api/src/`：

| 文件 | 职责 |
|---|---|
| `core/src/session/context_window.rs` | 计算 active context、auto-compact scope、剩余 token |
| `core/src/session/turn.rs` | pre-turn / mid-turn 自动压缩触发点 |
| `core/src/tasks/compact.rs` | 手动 `/compact` 任务入口，按 feature / provider 选择 local、remote、token-budget 路径 |
| `core/src/compact.rs` | local LLM summary compaction；生成 summary 后替换 history |
| `core/src/compact_remote.rs` | OpenAI 服务端 `/responses/compact` compaction |
| `core/src/compact_token_budget.rs` | TokenBudget feature 下的“开新 context window”式 compaction |
| `core/src/state/auto_compact_window.rs` | compaction window 编号、window id、prefill baseline |
| `codex-api/src/endpoint/compact.rs` | `POST responses/compact` 客户端 |

可以把 Codex 的 compaction 分成三条路径：

1. **Local compaction**：普通 LLM 调用，用本地 prompt 让模型总结，再把 history 替换成“最近 user 消息 + summary”。
2. **Remote compaction**：provider 支持时调用 OpenAI 的 `responses/compact` 专用 endpoint，服务端直接返回 compacted history。
3. **TokenBudget compaction**：feature 开启后不做 summarization，而是安装 fresh context window / world state，相当于“重开窗口”。

### 4.2 触发信号：90% context 或配置上限

```rust
// codex-rs/protocol/src/openai_models.rs
impl ModelInfo {
    pub fn auto_compact_token_limit(&self) -> Option<i64> {
        let context_limit = self
            .resolved_context_window()
            .map(|context_window| (context_window * 9) / 10);
        let config_limit = self.auto_compact_token_limit;
        if let Some(context_limit) = context_limit {
            return Some(
                config_limit.map_or(context_limit, |limit| std::cmp::min(limit, context_limit)),
            );
        }
        config_limit
    }
}
```

默认触发点是模型 context window 的 **90%**；如果 config 里设置了 `model_auto_compact_token_limit`，取 `min(config_limit, 90% context)`。

实际状态计算在 `context_window.rs`：

```rust
pub(crate) async fn context_window_token_status(
    sess: &Session,
    turn_context: &TurnContext,
) -> ContextWindowTokenStatus {
    let active_context_tokens = sess.get_total_token_usage().await;

    let (auto_compact_scope_tokens, auto_compact_scope_limit, body_window) =
        match turn_context.config.model_auto_compact_token_limit_scope {
            AutoCompactTokenLimitScope::Total => (
                active_context_tokens,
                turn_context.model_info.auto_compact_token_limit(),
                None,
            ),
            AutoCompactTokenLimitScope::BodyAfterPrefix => {
                let window = sess.auto_compact_window_snapshot().await;
                let baseline = window.prefill_input_tokens.unwrap_or(active_context_tokens);
                ...
                (active_context_tokens.saturating_sub(baseline), scope_limit, Some(...))
            }
        };

    let token_limit_reached = auto_compact_scope_limit
        .is_some_and(|limit| auto_compact_scope_tokens >= limit)
        || full_context_window_limit_reached;
}
```

**关键点**：Codex 支持两种计数 scope：
- `Total`：全 active context 都算进 compact budget。
- `BodyAfterPrefix`：只算当前 compaction window 中 prefix/baseline 之后增长出来的 body token，用 `prefill_input_tokens` 做基线扣除。这比“总 token 到阈值就压”更适合长线程 + prompt cache。

### 4.3 自动触发有 pre-turn 和 mid-turn 两个位置

Codex 不只在用户下一轮之前压缩，也会在同一轮工具循环中途压缩。

**Pre-turn**：进入新采样前先判断是否需要 compact。

```rust
// codex-rs/core/src/session/turn.rs
async fn run_pre_sampling_compact(...) -> CodexResult<()> {
    maybe_run_previous_model_inline_compact(sess, turn_context, client_session).await?;
    let token_status = context_window_token_status(sess.as_ref(), turn_context.as_ref()).await;
    if token_status.token_limit_reached {
        let step_context = sess.capture_step_context(Arc::clone(turn_context)).await;
        run_auto_compact(
            sess,
            step_context,
            client_session,
            InitialContextInjection::DoNotInject,
            CompactionReason::ContextLimit,
            CompactionPhase::PreTurn,
        ).await?;
    }
    Ok(())
}
```

**Mid-turn**：模型刚生成了 tool call、还有 follow-up 需求时，如果 token limit 达到，也先 compact 再继续下一次模型调用。

```rust
// codex-rs/core/src/session/turn.rs
let needs_follow_up = model_needs_follow_up || has_pending_input;

if needs_follow_up
    && (sess.take_new_context_window_request().await || token_limit_reached)
{
    run_auto_compact(
        &sess,
        Arc::clone(&step_context),
        &mut client_session,
        InitialContextInjection::BeforeLastUserMessage(Arc::clone(&world_state)),
        CompactionReason::ContextLimit,
        CompactionPhase::MidTurn,
    ).await?;
    continue;
}
```

Mid-turn 路径的 `InitialContextInjection::BeforeLastUserMessage` 很重要：压缩后还要继续当前工具循环，所以 Codex 会把 canonical initial context 插回 replacement history 中、且保持 last real user / summary 的位置符合模型训练期望。

### 4.4 Local compaction：LLM 总结 + history replacement

本地 compaction 的 prompt 很短，目标是生成 handoff summary：

```text
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
```

压缩完成后，Codex 不保留完整 assistant/tool 历史，而是构造 replacement history：

```rust
// codex-rs/core/src/compact.rs
let summary_suffix = get_last_assistant_message_from_turn(history_items).unwrap_or_default();
let summary_text = format!("{SUMMARY_PREFIX}\n{summary_suffix}");
let user_messages = collect_user_messages(history_items);

let mut new_history = build_compacted_history(Vec::new(), &user_messages, &summary_text);
...
sess.replace_compacted_history(
    turn_context.as_ref(),
    new_history,
    reference_context_item,
    world_state_baseline,
    compacted_item,
).await;
```

`build_compacted_history` 的策略是：保留最近 user messages（总计最多 20k tokens），再追加一条 summary user message：

```rust
const COMPACT_USER_MESSAGE_MAX_TOKENS: usize = 20_000;

fn build_compacted_history_with_limit(..., max_tokens: usize) -> Vec<ResponseItem> {
    for message in user_messages.iter().rev() {
        let tokens = approx_token_count(&message.message);
        if tokens <= remaining {
            selected_messages.push(message.clone());
            remaining = remaining.saturating_sub(tokens);
        } else {
            let truncated = truncate_text(&message.message, TruncationPolicy::Tokens(remaining));
            selected_messages.push(CompactedUserMessage { message: truncated, ... });
            break;
        }
    }

    for message in &selected_messages {
        history.push(ResponseItem::Message { role: "user".to_string(), ... });
    }

    history.push(ResponseItem::Message {
        role: "user".to_string(),
        content: vec![ContentItem::InputText { text: summary_text }],
        ...
    });
}
```

这点跟 OpenCode 不一样：OpenCode 更强调 structured 8-section summary；Codex 更强调“checkpoint handoff”，并额外保留最近 user 请求，防止 summary 把用户目标改写丢。

### 4.5 Remote compaction：OpenAI 专用 `responses/compact`

当 provider 支持 remote compaction 时，Codex 不用普通模型调用总结，而是发专用 API：

```rust
// codex-rs/codex-api/src/endpoint/compact.rs
fn path() -> &'static str {
    "responses/compact"
}

pub async fn compact_input(
    &self,
    input: &CompactionInput<'_>,
    extra_headers: HeaderMap,
    request_timeout: Duration,
    turn_state: Option<&OnceLock<String>>,
) -> Result<Vec<ResponseItem>, ApiError> {
    let body = serde_json::to_value(input)?;
    self.compact(body, extra_headers, request_timeout, turn_state).await
}
```

payload 是 canonical compaction input：

```rust
// codex-rs/codex-api/src/common.rs
pub struct CompactionInput<'a> {
    pub model: &'a str,
    pub input: &'a [ResponseItem],
    pub instructions: &'a str,
    pub tools: Option<Vec<Value>>,
    pub parallel_tool_calls: bool,
    pub reasoning: Option<Reasoning>,
    pub service_tier: Option<&'a str>,
    pub prompt_cache_key: Option<&'a str>,
    pub text: Option<TextControls>,
}
```

remote compaction 前还有一个很实用的兜底：如果历史太大，先把旧 tool/function output rewrite 成固定截断消息，确保 compact endpoint 自己能吃下输入。

```rust
// codex-rs/core/src/compact_remote.rs
fn rewritten_output_for_context_window(item: &ResponseItem) -> Option<ResponseItem> {
    Some(match item {
        ResponseItem::FunctionCallOutput { ... } => ResponseItem::FunctionCallOutput {
            output: truncated_output_payload(output),
            ...
        },
        ResponseItem::CustomToolCallOutput { ... } => ...,
        ResponseItem::ToolSearchOutput { ... } => ResponseItem::ToolSearchOutput {
            tools: Vec::new(),
            ...
        },
        _ => return None,
    })
}

const CONTEXT_WINDOW_TRUNCATED_OUTPUT_MESSAGE: &str =
    "Output exceeded the available model context and was truncated";
```

这是 Codex 的一个工程细节：**先轻量缩 tool output，让 compaction 请求本身不爆上下文**，再交给服务端做真正 compaction。

### 4.6 TokenBudget 路径：不总结，直接开新窗口

```rust
// codex-rs/core/src/compact_token_budget.rs
pub(crate) async fn run_inline_auto_compact_task(
    sess: Arc<Session>,
    step_context: Arc<StepContext>,
    initial_context_injection: InitialContextInjection,
) -> CodexResult<()> {
    let world_state = match initial_context_injection {
        InitialContextInjection::BeforeLastUserMessage(world_state) => world_state,
        InitialContextInjection::DoNotInject => {
            Arc::new(sess.build_world_state_for_step(&step_context).await)
        }
    };
    run_compact_task_inner(&sess, turn_context, world_state, CompactionTrigger::Auto).await
}

async fn run_compact_task_inner(...) -> CodexResult<()> {
    sess.emit_turn_item_started(turn_context, &compaction_item).await;
    sess.start_new_context_window(turn_context.as_ref(), world_state).await;
    sess.emit_turn_item_completed(turn_context, compaction_item).await;
    Ok(())
}
```

这条路径跳过模型/服务端 summarization，语义是“安装一个 fresh context window + 当前 world_state”。同时还可以在快到预算时注入 token budget reminder：

```rust
// codex-rs/core/src/session/token_budget.rs
if config
    .reminder_threshold_tokens
    .is_some_and(|threshold| tokens_until_compaction <= threshold)
{
    let response_item = ContextualUserFragment::into(TokenBudgetReminder::new(
        &config.reminder_message_template,
        tokens_until_compaction,
    ));
    sess.record_conversation_items(turn_context, std::slice::from_ref(&response_item)).await;
}
```

### 4.7 设计评价

- ✅ **触发点完整**：pre-turn + mid-turn 都能压缩，比只在回合边界判断更稳。
- ✅ **远端 compaction 是强产品化路径**：`responses/compact` 返回 replacement history，client 不需要自己解析 summary 格式。
- ✅ **TokenBudget / BodyAfterPrefix window**：能把“固定 prefix”从 compact budget 里扣掉，对 prompt cache 和长线程都友好。
- ✅ **compaction lifecycle 完整**：pre/post compact hooks、analytics、window id、rollout trace 都有一套事件模型。
- ✅ **remote 前先 rewrite 旧 tool output**：避免“连压缩请求本身都塞不进 context”的死局。
- ⚠ **local summary prompt 比 OpenCode 简单**：没有 8-section 硬模板，summary 质量更依赖模型。
- ⚠ **replacement history 主要保留 user messages + summary**：assistant/tool 细节靠 summary 承载，压缩质量差时容易丢实现细节。
- ⚠ **实现路径多**：local / remote / remote_v2 / token_budget 并存，调试时必须先确认当前 provider 和 feature flag 走哪条。

---

## 5. DeerFlow (bytedance/deer-flow, Python / LangGraph)

### 5.1 整体架构

DeerFlow 用 **LangGraph 中间件链**模式，每个上下文管理职责拆成独立 middleware，挂在 `langchain.agents.middleware.AgentMiddleware` 钩子上。相关 middleware（位于 `backend/packages/harness/deerflow/agents/middlewares/`）：

| Middleware | 行数 | 职责 |
|---|---|---|
| `token_budget_middleware.py` | 290 | 累计 token 跟踪 + warn/hard-stop 阈值 |
| `summarization_middleware.py` | 479 | 中段摘要（继承 LangChain `SummarizationMiddleware` + skill 救援）|
| `tool_output_budget_middleware.py` | 643 | 单个 tool 输出 token 预算 |
| `dynamic_context_middleware.py` | 307 | 动态注入提示（不是压缩，是把"系统提醒"以 HumanMessage 形式塞进对话）|

### 5.2 Token budget middleware（核心策略）

```python
# token_budget_middleware.py:65
class TokenBudgetMiddleware(AgentMiddleware[AgentState]):
    """Enforce per-run token budget limits.

    Detection strategy:
      1. After each model response, sum the `usage_metadata` of all `AIMessage`s
         in the current thread history. This automatically captures tokens from
         subagents because TokenUsageMiddleware retroactively adds them to history.
      2. If the highest fraction (input, output, or total) >= warn_threshold,
         queue a warning.
      3. If the highest fraction >= hard_stop_threshold, strip tool_calls.

    Warning injection uses the deferred pattern:
      - after_model queues the warning (does NOT mutate state).
      - wrap_model_call injects it as a HumanMessage at the next model call.
    This preserves AIMessage(tool_calls) → ToolMessage pairing.
    """
```

**关键设计**：

1. **三个独立预算**：`max_input_tokens` / `max_output_tokens` / `max_tokens(total)`，取占比最高那个触发
2. **Warn → Hard-stop 两级阈值**：`warn_threshold`（默认 0.8）注入警告 prompt，`hard_stop_threshold`（默认 0.95）直接 strip `tool_calls` 让模型立即收尾
3. **Deferred warning pattern**：在 `after_model` 队列里挂警告，**下次 `wrap_model_call`** 才注入为 `HumanMessage`。这样避免破坏 `AIMessage(tool_calls) → ToolMessage` 的配对完整性

警告 / Hard-stop 消息字面：

```python
_BUDGET_WARNING_MSG = (
    "[TOKEN BUDGET WARNING] You have used {used:,} of your {budget:,} {reason} "
    "token budget ({percent:.0f}%). Wrap up your current work and produce a "
    "final answer. Avoid starting new tool calls unless absolutely necessary."
)
_BUDGET_EXCEEDED_MSG = (
    "[TOKEN BUDGET EXCEEDED] The {reason} token usage ({used:,}) has exceeded "
    "the safety limit ({budget:,}). Producing final answer with results collected so far."
)
```

Hard stop 实现：

```python
def _build_hard_stop_update(self, msg: AIMessage, stop_msg: str) -> dict[str, Any]:
    """Build the state update dictionary for a hard stop."""
    updated_content = self._append_text(msg.content, stop_msg)
    kwargs = dict(msg.additional_kwargs) if msg.additional_kwargs else {}
    if "tool_calls" in kwargs: del kwargs["tool_calls"]      # ← 关键：剥 tool_calls
    if "function_call" in kwargs: del kwargs["function_call"]

    response_metadata = dict(getattr(msg, "response_metadata", {}) or {})
    if response_metadata.get("finish_reason") == "tool_calls":
        response_metadata["finish_reason"] = "stop"

    stopped_msg = msg.model_copy(update={
        "content": updated_content,
        "tool_calls": [],
        "additional_kwargs": kwargs,
        "response_metadata": response_metadata,
    })
    return {"messages": [stopped_msg]}
```

### 5.3 Subagent 累计追踪

```python
# 注释：
# This automatically captures tokens from subagents because
# TokenUsageMiddleware retroactively adds them to the history.

for msg in messages:
    if isinstance(msg, AIMessage) and msg.id and hasattr(msg, "usage_metadata"):
        usage = msg.usage_metadata or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        prev_input, prev_output = seen.get(msg.id, (0, 0))
        diff_input = max(0, input_tokens - prev_input)
        diff_output = max(0, output_tokens - prev_output)
        if diff_input > 0 or diff_output > 0:
            usage_accum.input += diff_input
            usage_accum.output += diff_output
            usage_accum.total += diff_input + diff_output
            seen[msg.id] = (input_tokens, output_tokens)
```

每条 AIMessage 用 `seen[msg.id] = (prev_input, prev_output)` 记忆上次值，diff 是新增 token —— 这样 subagent 调用回主 agent 时追加的 token 也被纳入。**这是其他三家都没有的能力**。

### 5.4 Summarization middleware

```python
# summarization_middleware.py:99
class DeerFlowSummarizationMiddleware(SummarizationMiddleware):
    """Summarization middleware with pre-compression hook dispatch and skill rescue."""
```

**直接继承 LangChain 自带的 `SummarizationMiddleware`**，只加了：
1. `BeforeSummarizationHook` 协议 → 让别的代码在摘要前介入
2. Skill rescue → 标记某些 tool call（带 skill 元数据）在摘要时不被丢弃

LangChain 自带 SummarizationMiddleware 的逻辑（社区项目）：基于 token 阈值，把超额的中段 messages 替换成一条 LLM 生成的 summary。

### 5.5 BoundedDict（防内存泄漏）

```python
class BoundedDict(OrderedDict):
    """A bounded dictionary to prevent unbounded state growth on abandoned runs."""
    def __init__(self, maxsize=1000, *args, **kwds):
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __setitem__(self, key, value):
        if key not in self:
            if len(self) >= self.maxsize:
                self.popitem(last=False)
        super().__setitem__(key, value)
```

middleware 状态按 `run_id` 隔离存储。**这是个 DeerFlow 才需要的问题** —— 因为它是个长跑服务（gateway 多 user 多 thread），其他三家是 CLI 单 session 不需要这种内存清理。

### 5.6 设计评价

- ✅ **可组合性最强**：上下文管理拆成 ~6 个 middleware，每个能独立测试、独立 enable/disable、独立配置
- ✅ **Warn → Hard-stop 两级阈值**：业内最完整的"温和提示 + 强制刹车"模式
- ✅ **Subagent token 累计**：唯一一家正确处理 subagent 用量回填的实现
- ✅ **Deferred warning pattern**：保护 tool_call 配对完整性的精细工程，反映 LangGraph 状态机的限制（不能在 after_model 直接插 HumanMessage）
- ✅ **BoundedDict + run_id 隔离**：服务端多用户多 run 场景的正确做法
- ⚠ **依赖 LangChain `SummarizationMiddleware`**：核心摘要逻辑不在自己手里，受上游迭代影响
- ⚠ **中间件链复杂**：6 个 middleware 的执行顺序、相互依赖（如 token_budget 依赖 token_usage 的 retroactive 写入）需要文档解释
- ⚠ **没有 placeholder 风格**：要么 LLM summarize 要么 hard-stop，没有更轻量的"删 tool 输出留 reasoning"中间档

---

## 6. 横向对比

### 6.1 设计维度

| 维度 | Claude Code | Hermes | OpenCode | Codex CLI | DeerFlow |
|---|---|---|---|---|---|
| **触发信号** | client + API server 双层 | `last_prompt_tokens >= threshold` | request 前估算 `tokens >= usable` | pre-turn / mid-turn `context_window_token_status` | `cumulative.total / max_tokens >= threshold` |
| **触发阈值** | 75% context (可调 env) | 32k 硬编码（各 engine） | `input_limit - 20k buffer` | 默认 90% context 或 `model_auto_compact_token_limit` | `warn=0.8 / hard=0.95`（可配） |
| **策略数量** | 1（auto-compact）+ tool 清理 | **4** (sliding_window/discard/summarize/visual) | 2 (prune + summary) | 3 (local summary / remote `/responses/compact` / token-budget window) | 2 (token_budget + summary) |
| **是否真删消息** | summary 替换 | discard 真删 / sliding 用占位符 / summarize 单条 summary 替换 | prune 真删 tool 输出 / summary 单条 summary 替换 | replacement history；local 保留 user + summary，remote 服务端返回 compacted history | summary 单条 summary 替换 |
| **保留头部** | system + first user | system + first 3 non-system | system | canonical initial context 可重新注入；local 不直接保留原 assistant/tool 头部 | system |
| **保留尾部** | "最近内容" (黑盒) | `protect_last_n=6` | `tail_turns=2` + 2k-8k budget | 最近 user messages 最多 20k tokens + summary；mid-turn 插回 world state | LangChain `SummarizationMiddleware` 内部决定 |
| **subagent 追踪** | ? | 各自 session | session 级 | 有 rollout trace / compaction window，但不是 DeerFlow 式全 thread token 回填 | ✅ 全 thread 累计 |
| **配置注入** | env var + json | yaml `context.strategy_config` | yaml `compaction.*` | config flags + provider capability + feature flags | per-middleware Python dataclass |
| **服务端兜底** | ✅ Anthropic API `compact_20260112` | ❌ | ❌ | ✅ OpenAI `responses/compact` | ❌ |
| **persistent memory** | CLAUDE.md + auto MEMORY.md | hermes-skills + memory tool | AGENTS.md | AGENTS.md + skills/memories（Codex repo 内置 skill system） | skills + memory_middleware |
| **代码可读性** | 闭源 | 中（多 engine 平铺） | 高（Effect-TS 单一职责） | 中（Rust 清晰，但 local/remote/token-budget 路径多） | 中（middleware 链需读懂 LangGraph） |
| **核心代码行数** | n/a | sliding 114 + discard 179 + summarize 803 + visual 700+ | overflow 34 + compaction 575 + summary 169 | compact 714 + remote 468 + token_budget 90 + context_window 92 | token_budget 290 + summary 479 |

### 6.2 设计风格归类

- **黑盒 + 服务端兜底**：Claude Code
- **插件化 engine（一个 session 选一个）**：Hermes
- **单一精心实现**：OpenCode
- **本地 client + 专用服务端 compact endpoint 混合**：Codex CLI
- **中间件链组合**：DeerFlow

五种风格代表了五种产品哲学：
- Claude Code 把复杂度推到 API 服务端 → 客户端简单
- Hermes 让用户选策略 → 灵活，适合做研究 baseline
- OpenCode 信任默认值 → 开箱即用，参数都是精挑细选的常量
- Codex CLI 把本地线程状态、服务端 compact、window 生命周期打通 → 产品化最完整
- DeerFlow 让框架来组合 → 适合企业级多团队定制

### 6.3 创新点排名

1. **Claude Code 服务端 compaction**：业内首创 API 层 compaction block；让所有客户端共享一份实现
2. **Codex remote compaction + mid-turn compaction**：`responses/compact` 专用 endpoint 加 pre-turn / mid-turn 双触发，产品化程度最高
3. **Hermes visual engine**：唯一把 trajectory 渲染成 PDF/PNG 喂 VLM 的实现，适合长 reasoning trace
4. **OpenCode summary template**：8 section markdown 硬约束 + Rules，输出可代码解析
5. **DeerFlow deferred warning + subagent retroactive token**：状态机+多 agent 的精细工程

### 6.4 共通教训

无论怎么实现，所有五家都遵循同样的几条原则：

1. **必须保留 system prompt + 第一个 user 消息**（任务上下文）
2. **必须保留最后 N 轮 / N tokens**（让模型能续推理）
3. **必须保护 `tool_call → ToolMessage` 配对**（API 400 防御）
4. **不要在压缩里改 system prompt**（破 prompt cache）
5. **触发前要 buffer**（留生成空间，约 4-20k token）

---

## 7. 对 Hermes 的具体建议

调研过程发现 Hermes 可以从其他几家学到几件事：

### 7.1 短期（小改动，可加分）

- **加 `force_final_answer` 兜底机制**（学 DeerFlow + DeepTraceHub）：当压缩失败或压缩后还超限时，剥 `tool_calls` 强制一次性收尾。当前 hermes 所有 engine 假设压缩成功能继续，没有这个最后防线。
- **summary engine 借鉴 OpenCode 的 8-section 模板**：当前 hermes 的 summary prompt 比较自由发挥，换成 OpenCode 这种硬约束模板能保证可解析性，方便下游统计。
- **`should_compress` 加 "请求前估算"** 路径（学 OpenCode）：当前用 `last_prompt_tokens`（上轮值），改成 `_estimate_messages_tokens(messages) >= threshold` 更准。
- **借鉴 Codex 的 pre-turn / mid-turn 双触发**：Hermes 现在更像“响应后发现上轮太长”；Codex 在下一次采样前和同一轮工具循环中途都能 compact，避免工具循环把窗口顶爆。

### 7.2 中期（结构调整）

- **`PRUNE_PROTECTED_TOOLS` 概念**（学 OpenCode）：标某些 tool 输出永不删（skill、plan、todo 之类），sliding_window/summarize 都该尊重。
- **Subagent token 累计**（学 DeerFlow）：当前 hermes subagent 的 token 用量不回到主 session 计数，长任务可能爆掉但不知道。需要在 `delegate_task` 返回时把 child 的 usage 加到 parent engine。
- **Warn / Hard-stop 两级阈值**（学 DeerFlow）：当前 hermes 只有 "threshold_tokens" 一个触发点；可以加 `warn_threshold` 在压缩前提醒模型自己 wrap up。
- **引入 Codex 的 compaction window / BodyAfterPrefix 计数思想**：把固定 system/tool schema/prefix 从增长预算中扣掉，只对窗口内新增长 token 触发压缩，更适合长线程和 prompt cache。

### 7.3 长期（探索方向）

- **服务端 compaction 跟进**（学 Claude Code）：当 Anthropic compact-2026-01-12 GA 时，hermes Anthropic provider 加 opt-in 支持，把上下文管理外包给 API。
- **OpenAI `responses/compact` 适配**（学 Codex）：如果 OpenAI/Codex provider 暴露稳定 compact endpoint，可以做 provider-specific remote compaction，避免本地 summary prompt 自己维护格式。
- **Visual engine 的 PDF 缓存**：当前每次压缩重渲染所有历史，可以增量缓存上次 compact_<N>.pdf，下次只追加新消息。

---

## 附：核心源码位置一览

| 项目 | 文件 |
|---|---|
| Hermes | `agent/context_engine.py`（ABC, 226 行）<br>`agent/context_compressor.py`（宿主, 2426 行）<br>`plugins/context_engine/{sliding_window,discard,summarize,visual}/__init__.py` |
| OpenCode | `packages/opencode/src/session/{overflow,compaction,summary}.ts`<br>`packages/core/src/session/{compaction,context-epoch}.ts` |
| Codex CLI | `codex-rs/core/src/session/{context_window,turn,token_budget}.rs`<br>`codex-rs/core/src/{compact,compact_remote,compact_token_budget}.rs`<br>`codex-rs/codex-api/src/endpoint/compact.rs`<br>`codex-rs/prompts/templates/compact/prompt.md` |
| DeerFlow | `backend/packages/harness/deerflow/agents/middlewares/{token_budget,summarization,tool_output_budget,dynamic_context}_middleware.py` |
| Claude Code | （闭源）`platform.claude.com/docs/en/build-with-claude/compaction`<br>`docs.claude.com/en/docs/claude-code/memory`<br>社区分析：https://hyperdev.matsuoka.com/p/how-claude-code-got-better-by-protecting |

---

调研日期：2026-06-26
