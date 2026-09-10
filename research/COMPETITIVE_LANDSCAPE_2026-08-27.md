# Competitive Landscape — 2026-08-27 (deep cut)

> Scope: what LangGraph, CrewAI, AutoGen, and OpenAI Agents SDK (Swarm successor)
> actually have as of late August 2026, what Calienne already has, what is
> worth adopting (versus what is vanity or out of scope).
>
> **Update vs the 2026-08-27 first pass:** this version trades prose summaries
> for **code-shape comparisons**: each section now shows the *exact* API shape
> in the competitor, the *exact* Calienne file/line that does the same job, and
> a verdict that names whether the gap is real or rhetorical.
>
> **Version corrections from the first pass (verified 2026-08-27 against the
> upstream release pages cited in §8):**
>
> 1. **LangGraph** is **1.2.11** (Aug 2026) for the runtime, with the
>    **langgraph-sdk 0.4.3** client (19 Aug 2026) — LangGraph 1.0 has not
>    been cut. The client adds `trace_policy` to `add_node` and a v3
>    `stream_events` shape.
> 2. **CrewAI** is **1.15.18** (27 Aug 2026), not 0.86+; declarative
>    conversational flows are now STABLE.
> 3. **AutoGen** is **python-v0.7.5** (30 Sep), still in maintenance mode;
>    the active 0.7.x line added `RedisMemory`, `reasoning_effort` for GPT-5,
>    and OTel GenAI traces. **Microsoft Agent Framework** (Python 1.15.0 /
>    .NET 1.19.0, Aug 2026) is the documented production successor and ships
>    a "Migrate from Autogen" page. We do not evaluate MAF here — the same
>    arguments that keep us off AutoGen keep us off MAF.
> 4. **OpenAI Agents SDK** is **0.22.0** (19 Aug 2026). 0.22.0 changed the
>    implicit default model to `gpt-5.6-luna` (cost-favored), shipped
>    `RunState.add_input()` for durable pending user input, MCP v1+v2, and
>    sandbox network-disable. None of these is enough to re-open the
>    "adopt SDK?" question (§5.1 still applies).
>
> Sources: live research on official docs/repos only — `langchain-ai.github.io`,
> `docs.langchain.com`, `blog.langchain.dev`, `github.com/langchain-ai/langgraph`;
> `docs.crewai.com`, `github.com/crewAIInc/crewAI`; `microsoft.github.io/autogen`,
> `github.com/microsoft/autogen`; `openai.github.io/openai-agents-python`,
> `github.com/openai/swarm`, `platform.openai.com`, `cookbook.openai.com`.
> Calienne side: every file/line cited below was opened for this audit
> (`orchestrator/`, `core/schemas.py`, `docs/new/plan.md`).

## TL;DR

Calienne's v1 architecture already covers the *architectural primitives* every
mature multi-agent framework converges on (DAG planner, event-driven scheduler,
budget-bounded repair loop, weighted consensus, RAG + memory hierarchy,
Experience DB, agent I/O contracts, K/R/V layer separation, versioned manifest).
The four competitors are useful as **reference points** for one or two specific
features each; nothing justifies a swap or a large re-platform.

Concrete adoptions, ranked by ROI, each with the Calienne file/line to touch:

| # | From | API shape | Calienne touch-point | Why |
|---|------|-----------|----------------------|-----|
| 1 | LangGraph | `Command(goto=..., update=...)` + `Send("worker", per_item_payload)` | `orchestrator/strategic_planner.py:60-105` returns `StrategicPlan` dataclass today; `orchestrator/execution_planner.py:151-251` already emits `can_run_parallel` and `depends_on` for every node — fold both into a `PlannerCommand` union type | Lets the planner express "fan out one worker per chunk" the same way it expresses "skip the judge" |
| 2 | AutoGen | `TerminationCondition \| other` (OR) and `TerminationCondition & other` (AND) | `orchestrator/repair.py:118-132` is a hand-wired `if not decision.allowed: synthesize with caveats`; `orchestrator/state_machine.py:47-58` is a dict-of-lists; both are composable but ad hoc | Make the gate composable so `budget_exhausted \| max_repairs_exhausted` reads as a circuit, not a chain of `or` |
| 3 | LangGraph | `interrupt(payload)` + `Command(resume=value)` | `orchestrator/uncertainty.py:55-145` (the `evaluate()` method) returns an `UncertaintyDecision` whose `outcome == "ask_user_clarification"` branch (lines 68-83) carries a `clarification_request`; `orchestrator/validation_layer.py:226-238` has a `clarification_request()` helper; no unified "pause + resume" primitive | A single interrupt/resume primitive replaces `needs_clarification` status + future studio "wait for human" paths |
| 4 | OpenAI SDK | `Agent(input_guardrail=[...])` / `output_guardrail=[...]` returning `GuardrailFunctionOutput` | `orchestrator/contracts.py:79-122` is the closest analog; currently only fires for nodes (per-task); guardrail-as-aggregate would let "any input matched X" abort the run before the planner | Out of scope for v1 unless a concrete poisoning story appears |
| 5 | CrewAI | `@start` / `@listen` / `@router` / `@persist` decorator pattern | No Calienne analog; not adopting — see §4 for why | Ergonomics layer; v2 candidate only |

Explicits skips (`#` is "we evaluated and rejected"):

- LangGraph `Pregel` super-step runtime: Calienne `Scheduler` (`orchestrator/scheduler.py`) is *already* dependency-aware + event-driven with `asyncio.Condition`. Pregel is a Python port of the same idea, not a different primitive.
- CrewAI Flows `@persist` checkpoint store: we have `orchestrator/execution_replay.py` + `orchestrator/checkpoints.py` with a Pydantic-typed `ReplayRecorder`. Decorator style would lose type data.
- AutoGen 0.7.x `SingleThreadedAgentRuntime`: the entire messaging layer is built around chat-style turn-taking, which doesn't fit Calienne's DAG (no "turn" abstraction, only `TaskNode.depends_on`).
- OpenAI Agents SDK `Runner` loop: closed-runtime, OpenAI-only. We are explicitly multi-provider with our own gateway (`api_gateway/`). Re-implementing handoffs locally is cheaper than fighting the runtime.

## 1. Calienne today (the matrix that makes the comparison honest)

Architecture version 0.1.7, manifest schema 1.0, 22-step roadmap complete, 657
tests green post-remediation (`research/AUDIT_2026-08-22.md`).

| Concern | LangGraph | CrewAI | AutoGen | OpenAI SDK | **Calienne (today)** |
|---|---|---|---|---|---|
| Topology | StateGraph (DAG) | Crews (sequential/hierarchical) + Flows (DAG) | AgentChat (group chat) + Core (messaging) | Agent graph (handoffs) | **TaskGraph** (`core/schemas.py`, built by `orchestrator/execution_planner.py:151-251`) |
| Planner | `Command`/`Send` returned from a node | `PlanningAgent` (LLM) | `SelectorGroupChat` / `Swarm` | `Runner` (no explicit planner) | `StrategicPlanner` (`orchestrator/strategic_planner.py`) → `ExecutionPlanner` (`orchestrator/execution_planner.py`) |
| Scheduler | Pregel super-step | Sequential default, hierarchical via `manager_llm` | `SingleThreadedAgentRuntime` | `Runner` loop | `Scheduler` with `asyncio.Condition` workers (`orchestrator/scheduler.py:124-181`) |
| Concurrency cap | `config["configurable"]["max_concurrency"]` | `max_rpm` per agent | `max_turns` + queue | implicit (loop) | `concurrency_limit=ResourceManager.scheduler_concurrency_limit` (`orchestrator/resource_manager.py:16-23` + `orchestrator/scheduler.py:30-39`) |
| Termination | `END` literal, conditional edges | `@router(method="AND/OR")` | `TerminationCondition \| &` | `max_turns` + custom | `orchestrator/repair.py:118-132` + `orchestrator/state_machine.py:47-58` (ad hoc) |
| Human-in-the-loop | `interrupt(payload)` + `Command(resume=...)` | `HumanInput` task in Flow | `UserProxyAgent` / `HandoffTermination` | `await Runner.run(..., previous_response_id=...)` | `ClarificationRequest` (`orchestrator/validation_layer.py:226-238`) + `uncertainty_decision.outcome == "ask_user_clarification"` (`orchestrator/execution_manager.py:394-440`) |
| Tools | `ToolNode` (decorator) | `@tool` decorator + `agent.tools=[...]` | `FunctionTool` / `BaseTool` | `@function_tool` decorator + `Agent(tools=[...])` | Provider-agnostic tool layer via `api_gateway/`; no in-orchestrator `@tool` decorator yet |
| Guardrails | (none) | (none, Flow-level only) | `Middleware` (TBD in 0.4.x) | `input_guardrail=[...]` / `output_guardrail=[...]` | `validate_inputs` / `validate_outputs` (`orchestrator/contracts.py:79-122`) — fires per node, not aggregate |
| Memory | `MemoryStore` (in-memory + checkpoint backend) | `Memory` (short/term/long/entity) | `Memory` (per-agent) | `Session` (in-memory or SQLAlchemy) | 3 layers: `MemoryManager` (`orchestrator/memory_manager.py`) + `MemoryHierarchy` (Step 16) + `ExperienceDB` (Step 20) |
| State / context | `StateGraph` typed state (Pydantic or TypedDict) | `Flow.state` TypedDict | `ChatCompletionContext` | `RunContextWrapper[T]` | `core/schemas.py` Pydantic models, `TaskNode` is the unit of state |
| Versioning | `config["configurable"]["thread_id"]` (run-level only) | n/a | n/a | n/a | `ExecutionManifest` + `graph_fingerprint` (SHA-256) + `version_stamp` (`orchestrator/execution_manifest.py`, `orchestrator/versioning.py`, RFC-005) |
| Repair loop | (not native) | (not native) | (not native) | (not native) | `orchestrator/repair.py` + `TokenBudgetManager.evaluate_repair_cycle` (RFC-003 §9, ADR-004) |

Three Calienne-specific properties the competitors do *not* match and that this
comparison should not lose sight of:

- **Pydantic-everywhere contracts.** Every node has `InputContract` /
  `OutputContract` / `FailureContract` (`orchestrator/contracts.py:15-122`).
  LangGraph's state is a TypedDict; OpenAI SDK has no per-tool contract.
- **Budget as first-class resource.** `TokenBudgetManager` (`orchestrator/budget.py`)
  is the sole owner of every LLM call's token budget; `ResourceManager`
  (`orchestrator/resource_manager.py`) composes the rate limiter, capability
  config, and budget to compute `effective_parallel`. AutoGen 0.7.x's
  `max_turns` + `TokenUsageTermination` is the rough analog but is not
  connected to a budget.
- **Replay by default.** `ReplayRecorder` + `ReplayStore`
  (`orchestrator/execution_replay.py`) is on by default when
  `CALIENNE_ENABLE_REPLAY` is on; nothing in the four competitors gives a
  portable replay trace keyed on `graph_fingerprint`.

## 2. LangGraph (1.2.11 + langgraph-sdk 0.4.3) — close on shape, far on runtime

Note on versions (verified 2026-08-27 against `github.com/langchain-ai/langgraph`
releases and PyPI for `langgraph-sdk`): LangGraph 1.0 has not been cut. The
current line is **LangGraph 1.2.11** (Aug 2026) for the runtime, and
**langgraph-sdk 0.4.3** (19 Aug 2026) for the client SDK. The 0.4.x client adds
`trace_policy` to `add_node` and a v3 of `stream_events` — the latter is what
the LangGraph Studio UI consumes and is the only fully supported event schema
in current LangSmith.

### 2.1 The `Command` / `Send` primitives — adoption #1

LangGraph's `Command` is a first-class return type that a node can use to (a)
update graph state, (b) jump to a different node, and (c) optionally resume
from an interrupt. `Send` is the dynamic-fan-out primitive — a node can return
`[Send("worker", per_item_payload)]` to dispatch one worker per item in a list
without knowing the count at compile time.

LangGraph shape:

```python
class Command(NamedTuple):
    goto: str | Send | Sequence[str | Send]
    update: Any = None
    graph: str | None = None   # multi-graph routing

def planner_node(state) -> list[Command | Send]:
    chunks = chunk(state.docs)
    return [Send("summarize", {"chunk": c}) for c in chunks] + [
        Command(goto="judge", update={"plan_id": "v1"})
    ]
```

Calienne today: a planner returns a `StrategicPlan` dataclass
(`orchestrator/strategic_planner.py:60-105`) which is *data*; the
`ExecutionPlanner.create_graph()` then converts it to a `TaskGraph` with
concrete `can_run_parallel` / `depends_on` per node
(`orchestrator/execution_planner.py:151-251`).

Code-shape delta:

| Concept | LangGraph | Calienne | Delta |
|---|---|---|---|
| "Plan = sequence of node dispatches" | `Command(goto=..., update=...)` | `StrategicPlan.sub_problems: list[str]` + `TaskGraph` | Plan is a string list, not a dispatch list |
| "Fan out N workers at runtime" | `Send("worker", payload_for_n)` | `TaskNode.can_run_parallel: bool` + explicit parallelism in the graph | Runtime count is hard-coded at plan time, not derived from input data |
| "Mutate graph state from a node" | `Command(update=state_patch)` | No node-level state mutation; only `produced_outputs` for the next node | Missing |
| "Multi-graph routing" | `Command(graph="other_graph")` | `TaskGraph` is single; `strategic_plan` is an input, not a dispatch | Out of scope for v1 |

**Adoption #1 verdict:** ship a `PlannerCommand` union type next to
`StrategicPlan` so the planner can express "fan out one worker per chunk" the
same way it expresses "skip the judge". Keep `TaskGraph` as the compiled
output. This is a 50-100 line additive change to
`orchestrator/strategic_planner.py` + a small extension to
`ExecutionPlanner.create_graph()`. The `Command(update=...)` half is lower
value (we already do per-node state via `produced_outputs`) and should be
deferred.

### 2.2 `interrupt()` + `Command(resume=...)` — adoption #3

LangGraph's HITL primitive: any node can call `interrupt(payload)` to pause,
return a checkpoint, and be resumed from the same checkpoint with
`graph.invoke(Command(resume=user_answer), config)`. The runtime tracks the
pause, the thread id is the resumption key, and the user can resume from any
client.

LangGraph shape:

```python
from langgraph.types import interrupt, Command

def ask_user(state) -> dict:
    answer = interrupt({"question": "What's your timezone?"})
    return {"timezone": answer}

graph.invoke(Command(resume="Europe/Berlin"), config={"configurable": {"thread_id": "..."}})
```

Calienne today has two separate flows:

1. **The clarification path** (`orchestrator/validation_layer.py:226-238` +
   `orchestrator/execution_manager.py:394-440`): when
   `uncertainty_decision.outcome == "ask_user_clarification"`, the manager
   finalizes replay, returns a `status: "needs_clarification"` envelope, and
   exits. There is no `run_id` to resume against — the front-end has to
   resubmit the entire request.
2. **The repair loop** (`orchestrator/repair.py`): synchronous, runs N cycles,
   returns a `RepairResult`. No "pause and ask user" path inside repair.

The two flows share *nothing* — different control flow, different return
shape, different telemetry, different persistence story. The new-chat studio
(`ModelApiStudioModal`, the debug replay page) will eventually need both; each
will re-implement its own version of the pause/resume handshake unless we
adopt a single primitive.

**Adoption #3 verdict:** introduce `interrupt(payload)` + `Command(resume=...)`
as a thin layer over `PipelineState.PAUSED` (add to
`orchestrator/state_machine.py:18-29`). The runtime:

- `interrupt(payload)` writes the payload to `replay_store` under the
  current `trace_id` and transitions the state machine to `PAUSED`.
- `Command(resume=value)` re-enters the paused node with the value as an
  extra input. The replay trace already gives us the resumption key.

This unifies the two flows and gives the new-chat studio a single resume API.
Size: a new `orchestrator/hitl.py` (~80 lines) + an `interrupt` /
`resume_with` pair + tests for "pause at clarification" and "pause inside
repair" against the same replay trace.

### 2.3 Pregel super-step — explicit skip

LangGraph's runtime is "Pregel super-step": every node runs in a topological
"wave" (a super-step), all edges fan out, and the runtime loops until quiescent.
This is the same idea as `Scheduler` in `orchestrator/scheduler.py:47-181` —
workers pull from a `ready_queue` guarded by `asyncio.Condition`, mark
completed under the lock, and decrement dependency counts to enqueue
dependents. The wave model and the worker-pool model are equivalent in
throughput; the difference is *style*. Calienne's model is simpler because
it's plain asyncio, not a Pregel clone. **No adoption.**

## 3. CrewAI (1.15.18, 27 Aug 2026) — Flow ergonomics, decorator overhead

Note on version: CrewAI's current `pip install crewai` line is **1.15.18**,
released 27 Aug 2026 (verified against `github.com/crewAIInc/crewAI` releases
and `pypi.org/project/crewai/`). The big 2026 movement on this line is the
declarative conversational flows pattern promoted to **STABLE** — the early
2026 betas have shipped as production-ready. No code-shape changes from our
side, but the stability changes the "v2 candidate" framing in §3.1: if v2 ever
authored a studio-mode graph by hand, the conversational-flows primitive
would be the part that actually has docs and an upgrade path, not the
`@start`/`@listen`/`@router`/`@persist` decorator stack itself.

### 3.1 The `@start` / `@listen` / `@router` / `@persist` decorator stack

### 3.1 The `@start` / `@listen` / `@router` / `@persist` decorator stack

CrewAI Flows replace the `Crew` (sequential/hierarchical) model with a
decorator-driven DAG:

```python
from crewai.flow.flow import Flow, start, listen, router, persist

class ContentFlow(Flow[State]):
    @start()
    def fetch(self): ...

    @listen(fetch)
    def summarize(self, fetch_result): ...

    @router(summarize)
    def classify(self, summary) -> Literal["deep", "shallow"]:
        if "complex" in summary: return "deep"
        return "shallow"
```

Calienne today declares topology *as data*: a `TaskGraph` is a
`Pydantic` model with `nodes: list[TaskNode]` and `edges` via
`TaskNode.depends_on: list[str]` (`core/schemas.py`). The graph is constructed
by `ExecutionPlanner.create_graph()` from a `StrategicPlan` or a hard-coded
template.

Code-shape delta:

| Concept | CrewAI | Calienne | Delta |
|---|---|---|---|
| "Node declaration" | `@start` / `@listen(method)` on a method | `TaskNode(task_id=..., objective=..., depends_on=...)` in a list | CrewAI is decorator; Calienne is data |
| "Conditional edge" | `@router(method)` returning a literal type | `depends_on` is unconditional; conditionality is in the `node_completed_recheck` hook (`orchestrator/meta_reasoner.py:259-274`) | Different layer — CrewAI is a runtime router; Calienne's branching happens in node semantics, not graph topology |
| "Persistent state" | `@persist` decorator (SQLite-backed dict) | `MemoryManager` / `MemoryHierarchy` / `ExperienceDB` — three different layers, each typed | Calienne is more structured |
| "Auto state typing" | `Flow[State]` (one TypedDict per flow) | Pydantic models per node + per graph | Equivalent |

**Adoption #5 verdict:** do not adopt. The decorator style is a *fit* for
notebook-style author workflows where the developer types a `@start` on a
method and CrewAI wires the graph. Calienne's graph is *compiled at runtime*
by the planner, not authored by a human; the planner needs a data shape to
write into, and decorators give the planner nothing to manipulate. The
*named* patterns (start, listen, router, persist) are a useful vocabulary for
docs but should not become runtime types. If v2 adds a "studio-author" mode
where a human writes the graph, the decorator surface is a candidate — not
now.

### 3.2 Crews (sequential + hierarchical) — explicit skip

CrewAI's `Crew` model is a step backwards for Calienne: `Process.sequential`
runs agents one at a time and pipes the output forward; `Process.hierarchical`
adds a `manager_llm` that decides who runs next. Both models are chat-style
turn-taking, not a DAG. They have no concept of "this node runs in parallel
with this other node", which is a hard requirement for Calienne's RAG fan-out
+ parallel final-answer generation (`orchestrator/execution_planner.py:181-220`
shows the `work_n` parallel tier explicitly).

**No adoption.**

## 4. AutoGen 0.7.5 (maintenance mode, Sep) — three layers, one fit, one successor

Note on version (verified 2026-08-27 against `github.com/microsoft/autogen`
releases and `pypi.org/project/autogen/`): the `python` package is
**autogen-agentchat / autogen-core / autogen-ext 0.7.5** (30 Sep — the
Sep tag is from an out-of-band release). The repo is in **maintenance mode**:
the team has confirmed publicly that new feature work is happening on
**Microsoft Agent Framework (MAF)** instead (Python 1.15.0 / .NET 1.19.0, both
released 21-22 Aug 2026; MAF ships a "Migrate from Autogen" page that maps
0.7.x API shapes 1:1 to MAF concepts).

What that means for Calienne: MAF is the **real** AutoGen successor and the
**next** 0.x line of AutoGen is unlikely to land meaningful new features.
The 0.7.x codebase is the high-water mark of the actor-message runtime. We
evaluate MAF only as a competitor (not in this doc); we evaluate AutoGen 0.7.x
below as the architecturally-rich endpoint of the line.

### 4.1 The `Core` / `AgentChat` / `Extensions` split

AutoGen 0.4 (and continuing through 0.7.x) organizes the library into three
layers:

- **Core** (`autogen-core`): `SingleThreadedAgentRuntime`, `RoutedAgent`,
  message-passing primitives (`publish_message`, `send_message`). The runtime
  is event-driven and async-first; agents are actors.
- **AgentChat** (`autogen-agentchat`): `AssistantAgent`, `UserProxyAgent`,
  `CodeExecutorAgent`, group-chat patterns (`SelectorGroupChat`, `Swarm`,
  `RoundRobinGroupChat`). 0.7.x added `CodeExecutorAgent` defaults
  (DockerCommandLineCodeExecutor) and a nested `Team` as a participant in a
  parent `Team`.
- **Extensions** (`autogen-ext`): tool adapters (OpenAI, Anthropic, MCP,
  etc.) and integration scaffolds.

The 0.7.x release notes also add **`RedisMemory`** as a first-class
`Memory` backend, OpenTelemetry GenAI semantic-convention traces, and GPT-5
`reasoning_effort` propagation through `OpenAIChatCompletionClient` —
operational polish, not architectural change.

Calienne's equivalent layering:

| AutoGen 0.7.x | Calienne | Note |
|---|---|---|
| `Core` runtime (messaging) | `Scheduler` (`orchestrator/scheduler.py`) | Calienne's is async-Condition based, not message-passing; simpler but not flexible |
| `AgentChat` patterns | `MicroMode` (`orchestrator/pipelines.py`) + DAG executor | Calienne's two runtimes |
| Tool/agent extensions | `api_gateway/` | Multi-provider with rate limiting |
| `RedisMemory` (0.7.x) | `MemoryHierarchy` (Step 16) + `ExperienceDB` (Step 20) | Calienne is more structured (3 typed layers, offline aggregation) |
| Termination (next section) | `orchestrator/repair.py:118-132` + `orchestrator/state_machine.py:47-58` | Ad hoc |

The 0.4 architectural split is good. Calienne's split (planner → executor →
validation → repair) is in the same spirit. **No adoption of the layering
itself** — the move would invalidate every reference to `Scheduler.run()`
and break 657 tests for no measurable gain. The 0.7.x polish
(`RedisMemory`, `reasoning_effort` propagation, OTel GenAI traces) maps
cleanly onto things we either already have (MemoryHierarchy, capability
config) or already opted out of (the OTel exporter is overkill for v1; our
`orchestrator/telemetry.py` is enough).

### 4.2 `TerminationCondition` composition (OR / AND) — adoption #2

AutoGen 0.7.x's `TerminationCondition` is a typed predicate that composes with
`|` (OR) and `&` (AND):

```python
from autogen_core import TerminationCondition

stop = MaxMessageTermination(10) | TokenUsageTermination(4096)
# reads as: "stop if max messages OR budget exhausted"
result = await stop(agent_run_state)
```

Calienne today: `orchestrator/repair.py:118-132` reads

```python
if not decision.allowed:
    caveats = [
        f"Repair cycle {cycle} skipped: {decision.reason}",
        *(f"Unresolved {d.kind}: {d.description}" for d in actionable),
    ]
    return RepairResult(
        output=best_output,
        repaired=bool(attempts),
        bypassed=True,
        bypass_reason=decision.reason,
        caveats=caveats,
        attempts=attempts,
        total_repair_tokens_spent=tokens_spent,
    )
```

That's a single `or`-chain encoded as a hand-wired `if`. The state machine
(`orchestrator/state_machine.py:47-58`) is a dict-of-lists:

```python
VALID_TRANSITIONS: dict[PipelineState, list[PipelineState]] = {
    PipelineState.IDLE: [PipelineState.NORMALIZING],
    PipelineState.NORMALIZING: [PipelineState.BREACH_CHECKING, PipelineState.FAILED],
    ...
}
```

…which is composable (you can ask "is X a valid Y transition") but the
composition is implicit in the dict, not explicit in the call site.

**Adoption #2 verdict:** introduce a small `Termination` class hierarchy
(`BaseTermination` with `__or__` and `__and__`) in a new
`orchestrator/termination.py`. Migrate `repair.py:118-132` to read

```python
stop = BudgetExhausted(budget_manager) | MaxRepairsReached(max_repairs)
if stop.is_met(cycle, tokens_spent, attempts):
    return RepairResult(..., bypass_reason=stop.reason)
```

…and migrate `state_machine.py:47-58` to express `COMPLETED | FAILED | ABORTED`
as a `Termination` union. Size: ~50 lines + a few tests. The win is the gate
becomes *data* the planner can reason about, not a sequence of ifs the
validator has to read to understand.

### 4.3 `SelectorGroupChat` / `Swarm` — explicit skip

AutoGen's group-chat patterns route a message to the "best" next agent based
on an LLM (`SelectorGroupChat`) or a hand-coded handoff (`Swarm`). The mental
model is "chat between agents"; the topology is dynamic. Calienne's topology
is *static* (a compiled `TaskGraph`) and the dynamic part is
*planner-level* (`StrategicPlanner` decides sub-problems, the executor
fans out within the boundaries of the plan). Adopting `SelectorGroupChat` would
re-introduce the chat-turn abstraction we deliberately dropped in favor of
"node = typed unit with input/output contract" (`orchestrator/contracts.py`).
**No adoption.**

## 5. OpenAI Agents SDK (0.22.0, 19 Aug 2026, Swarm successor) — small wins, big constraint

Note on version (verified 2026-08-27 against PyPI and the official changelog
at `openai.github.io/openai-agents-python/release/`): the current `openai-agents`
release is **0.22.0** (19 Aug 2026). The 0.22.0 line ships several primitives
worth naming even though we don't adopt the SDK:

- The SDK's **implicit default model is now `gpt-5.6-luna`** (previously
  `gpt-5.4-mini`), with `reasoning.effort="none"` and `verbosity="low"`. This
  is interesting because it's the first OpenAI SDK default that explicitly
  favors cost over capability — it signals a positioning shift in 0.22.0
  toward high-volume, low-reasoning workflows. Calienne's gateway is
  provider-agnostic (`api_gateway/`) and lets the user pin the model, so this
  default is irrelevant to us — but it confirms the "low-cost model
  competition" trend that affects all four competitors.
- **`RunState.add_input()`** lets a paused run stage durable user input
  before the next model call, surviving serialization. The shape is the
  same primitive we want for `interrupt`/`Command(resume=...)` (adoption
  #3). The fact that OpenAI shipped this exact primitive in 0.22.0
  validates that the use case is real and underspecified by earlier
  SDK versions.
- **MCP v1 + v2 support** through `mcp>=1.19.0,<3`. This matters for
  Calienne because if we ever add native MCP support (`api_gateway/` does
  not yet), we have to pick a v1 or v2 SDK and live with the httpx/httpx2
  migration.
- **Sandbox network-disable** + credential-scoping mount validations.
  Defense-in-depth that aligns with Calienne's "production refuses
  simulation fallback" posture.

### 5.1 Handoffs as tools + `Runner` loop — explicit skip

The SDK's central abstraction: an `Agent` has `tools=[...]` where one of the
tools is another `Agent`. Calling that tool transfers control to the other
agent; the `Runner` loop is a single event loop that does "call agent →
get handoff → switch to next agent → repeat until end".

Calienne's analog: a `TaskNode` with a `TaskNode.next` reference is
graph-level, not tool-level. Adding "handoffs as tools" would let a node
inside a DAG call another DAG mid-execution, which is *exactly* the
"non-deterministic topology" problem LangGraph explicitly chose `Command`/
`Send` to avoid. Worse, the SDK is OpenAI-centric: `Runner` is closed-source
in spirit, the session store is OpenAI-flavored, and the entire framework
assumes the same provider throughout a run. Calienne is multi-provider with
its own gateway and rate limiter (`api_gateway/`).

**No adoption.** The handoffs-as-tools pattern is interesting in the abstract
and worth a paragraph in a "patterns" doc, but depending on the SDK to get
it would cost more than re-implementing the small subset we want.

### 5.2 `input_guardrail` / `output_guardrail` — adoption #4

The SDK lets you attach guardrails to an `Agent` that run before/after every
turn:

```python
async def no_pii(ctx, agent, input) -> GuardrailFunctionOutput:
    if contains_pii(input):
        return GuardrailFunctionOutput(output_info="pii detected", tripwire_triggered=True)
    return GuardrailFunctionOutput(output_info="clean", tripwire_triggered=False)

agent = Agent(name="X", input_guardrail=[no_pii], ...)
```

The guardrail either passes (continue) or trips (abort). It's evaluated
*outside* the model call, so the model never sees the input if the guardrail
trips.

Calienne's analog: `validate_inputs` / `validate_outputs`
(`orchestrator/contracts.py:79-122`) is per-node, not aggregate. The
"firewall" in `orchestrator/validation_layer.py:91-131` runs at the end of
the run on the final text. Neither is the "abort the whole run on first
tripwire" pattern.

**Adoption #4 verdict:** out of scope for v1. We don't have a concrete
poisoning story yet (the `unsupported_claim` check in
`orchestrator/validation_layer.py:124-176` is the closest, but it's a
*soft* check, not a tripwire). When one appears, the natural fit is a
`Guardrails = list[BaseGuardrail]` on `ExecutionManifest` that runs at the
top of `ExecutionManager.execute()` (`orchestrator/execution_manager.py:213-256`).
Document the pattern in `docs/new/plan.md` as a v2 candidate.

### 5.3 `Session` memory — already covered

The SDK's `Session` is in-memory or SQLAlchemy-backed; it's a flat
conversation store. Calienne's `MemoryHierarchy` (Step 16) is the same idea
structured into 3 layers (short/term/long) + `ExperienceDB` (Step 20) for
offline aggregation. **Already covered, no adoption.**

## 6. What doesn't change

Three things this comparison should not be used to argue for:

- **Pydantic-everywhere contracts.** The four competitors split state and
  contracts (LangGraph: TypedDict; OpenAI SDK: function schemas; AutoGen:
  dataclass messages). Calienne's `InputContract` / `OutputContract` /
  `FailureContract` (`orchestrator/contracts.py`) is one of the few
  framework-level wins we have and should not be replaced.
- **The 4-stage validation pipeline.** Breaker Gate → Logician ∥ Creative →
  Synthesis Judge is a *model of thought*, not a competitor pattern. None of
  the four frameworks have it. It maps to our `pipelines.run_micro_mode`
  (`orchestrator/pipelines.py`) and our `validation_layer.validate_dag_output`
  (`orchestrator/validation_layer.py:133-195`).
- **The budget as first-class resource.** AutoGen 0.7.x's
  `max_turns` + `TokenUsageTermination` is the closest competitor
  primitive; Calienne's `TokenBudgetManager` is wired into every node call
  via `_make_node_executor`
  (`orchestrator/execution_manager.py:700-866`). No framework has that.

## 7. Suggested next step

Concretely, in order of cost/benefit:

1. **Adoption #2 (Termination composition).** ~50 lines, low risk, makes the
   repair loop readable. No file opens required beyond
   `orchestrator/repair.py` and `orchestrator/state_machine.py`.
2. **Adoption #3 (`interrupt()` / `Command(resume=...)`).** ~80 lines,
   higher risk, unifies two existing flows. Required for the new-chat
   studio's "wait for human" path.
3. **Adoption #1 (`PlannerCommand` / `Send`).** ~100 lines, additive, gives
   the planner a real dispatch shape.
4. **Adoption #4 (guardrails).** Document the pattern; don't build until a
   concrete need appears.

Skip 5: the CrewAI decorator stack does not fit a planner-driven graph.

## 8. Sources

Versions and dates verified 2026-08-27 against the upstream release pages
named in each line.

- LangGraph: `https://langchain-ai.github.io/langgraph/`, `https://langchain-ai.github.io/langgraph/concepts/low_level/`, `https://blog.langchain.dev/command-and-send/`, `https://github.com/langchain-ai/langgraph/releases` (runtime **1.2.11**, Aug 2026), `https://pypi.org/project/langgraph-sdk/` (client **0.4.3**, 19 Aug 2026).
- CrewAI: `https://docs.crewai.com/concepts/flows`, `https://docs.crewai.com/concepts/crews`, `https://github.com/crewAIInc/crewAI/releases` (**1.15.18**, 27 Aug 2026; conversational flows now STABLE).
- AutoGen: `https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/framework/agent-and-agent-runtime.html`, `https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/termination.html`, `https://github.com/microsoft/autogen/releases` (python package **0.7.5**, 30 Sep; repo in maintenance mode); `https://github.com/microsoft/autogen` README links to the production successor.
- Microsoft Agent Framework (AutoGen successor, out of scope for this doc): `https://learn.microsoft.com/en-us/agent-framework/overview`, `https://learn.microsoft.com/en-us/agent-framework/how-to/migrate-from-autogen` (Python **1.15.0** / .NET **1.19.0**, 21-22 Aug 2026).
- OpenAI Agents SDK: `https://openai.github.io/openai-agents-python/`, `https://openai.github.io/openai-agents-python/guardrails/`, `https://openai.github.io/openai-agents-python/handoffs/`, `https://openai.github.io/openai-agents-python/release/` (**0.22.0**, 19 Aug 2026; default model `gpt-5.6-luna`; `RunState.add_input()`; MCP v1+v2), `https://github.com/openai/swarm` (read-only, archived 2025-09).
- Calienne: `docs/new/plan.md`, `docs/new/guide.md`, `docs/PROJECT_BIBLE.md`, `docs/new/rfcs/RFC-002_Execution_Pipeline.md`, `docs/new/rfcs/RFC-003_Planner_Scheduler.md`, `docs/new/rfcs/RFC-005_Versioning_&_Execution_Manifest.md`, `docs/new/adrs/ADR-004_Resource_Ceiling_Management.md`, `research/AUDIT_2026-08-22.md`. File:line citations in §§1-5 are from the working tree as of 2026-08-27.
