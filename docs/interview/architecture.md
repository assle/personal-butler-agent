# Personal Butler Agent — Architecture Diagrams

## Overall System Architecture

```mermaid
flowchart LR
    subgraph WeChat["WeChat Work"]
        CB[Intelligent Robot<br/>URL Callback]
        WH[Group Webhook]
        CA[Custom App API]
    end

    subgraph FastAPI["FastAPI Producer"]
        CR[callback_router]
        IH[callback_inbox<br/>idempotent]
        CH[callback_handler]
        DISP[dispatch_message]
        SI[Submission Interface]
        SQ[Status Query]
    end

    subgraph Scene["Scene Agents<br/>(LangGraph StateGraph)"]
        PBA[PrivateButlerAgent<br/>15 tools, ReAct loop]
        GMA[GroupMentionAgent<br/>classified routing]
    end

    subgraph Domain["Domain Agents"]
        SUM[SummaryAgent]
        REM[ReminderAgent]
        POLL[PollAgent]
        MEM[MemoryService]
    end

    subgraph Research["Async Research Pipeline<br/>(PostgreSQL DAG + Taskiq)"]
        RQ[Redis Stream<br/>Task Queue]
        SUP[Supervisor<br/>LLM planner]
        SPE[Specialists<br/>KB + Web]
        SYN[Synthesizer<br/>Evidence-grounded]
        REV[Reviewer<br/>Citation check]
        QG[Quality Gate<br/>Deterministic + repair]
        DEL[Delivery<br/>Custom app push]
    end

    subgraph Storage["Persistence"]
        PG[(PostgreSQL<br/>Alembic-managed)]
        CHROMA[(ChromaDB<br/>vector index)]
        RD[(Redis<br/>queue + circuit breaker)]
    end

    CB -->|POST/GET| CR
    CR --> IH
    IH --> CH
    CH --> DISP
    DISP -->|private| PBA
    DISP -->|group| GMA
    PBA --> Domain
    GMA --> Domain

    DISP -->|research<br/>submission| SI
    SI --> RQ
    SQ --> PG

    RQ --> SUP
    SUP --> SPE
    SPE --> SYN
    SYN --> REV
    REV --> QG
    QG --> DEL
    DEL --> CA

    PBA --> PG
    GMA --> PG
    Domain --> PG
    SPE --> CHROMA
    Research --> PG
    Research --> RD

    WH -->|scheduled push| WH
```

## Research Pipeline Sequence

```mermaid
sequenceDiagram
    participant User as User (WeChat)
    participant API as FastAPI Producer
    participant PG as PostgreSQL
    participant Redis as Redis Stream
    participant Worker as Taskiq Worker
    participant LLM as DeepSeek API

    User->>API: 深度研究：topic
    API->>PG: create_task(status=queued)
    API->>Redis: enqueue(task_id)
    API-->>User: 研究任务已提交

    Worker->>Redis: claim task_id
    Worker->>PG: mark_running

    Worker->>LLM: plan(query, skills)
    LLM-->>Worker: PlanDraft (steps)
    Worker->>PG: save_plan

    loop Each Step
        Worker->>Worker: execute_step
        Worker->>LLM: retrieve + analyze
        LLM-->>Worker: evidence
        Worker->>PG: persist_evidence
        Worker->>Worker: check_budget
    end

    Worker->>LLM: synthesize(evidence, claims)
    LLM-->>Worker: ResearchReport

    Worker->>LLM: review(citations)
    LLM-->>Worker: ReviewFindings
    Worker->>Worker: quality_gate

    alt Gate Fails
        Worker->>LLM: repair(max_rounds)
        LLM-->>Worker: revised claims
        Worker->>Worker: re-check gate
    end

    Worker->>PG: complete_with_report

    Worker->>Redis: enqueue_delivery
    Worker->>LLM: delivery(poll)

    User->>API: 查看研究任务 R-xxx
    API->>PG: query_status
    API-->>User: 研究已完成，正在投递

    Worker->>Worker: deliver(custom_app)
    Worker->>PG: mark_delivered
    Worker-->>User: 研究报告推送
```

## Trade-off Notes

### PostgreSQL Authoritative vs Redis Transport

- **PostgreSQL is authoritative**: all task state, plans, evidence, and reports live in PG. The Redis Stream carries only the task_id. If Redis loses the queue, workers re-query PG and recover. This prevents split-brain between queue state and DB state.
- **Redis is a transport, not a store**: we use it for producer-worker decoupling, not state persistence. Feature-gated (`RESEARCH_ENABLED` defaults false) to preserve zero-dependency startup.
- **Trade-off**: SQLite concurrent writers (API + 3 workers) may show `database is locked` under high load. PostgreSQL migration (Alembic-managed) addresses this.

### LangGraph for Scene Agents vs Durable DAG for Research

- **LangGraph StateGraph**: ideal for interactive agents where latency matters (sub-second ReAct loops). Checkpointing via MemorySaver gives multi-turn conversation memory. Every user message enters a fresh graph invocation.
- **Durable DAG (PostgreSQL rows)**: research steps are first-class DB entries with leases. Workers claim via row locks. Expired leases auto-recover. Plans are versioned and side-effect-free until approved.
- **Why not use LangGraph for research**: research runs can take minutes, involve multiple LLM calls, and span process boundaries (producer -> queue -> worker). LangGraph's StateGraph is designed for in-process, single-invocation agent loops. PostgreSQL rows with leases provide the durability and recovery that async workflows need.
- **Why not use DAG for scene agents**: scene agents respond to user messages in < 3 seconds. Writing each tool call as a DB step would add unacceptable latency. The DAG overhead (leases, row locks, recovery) is unnecessary when the agent completes in a single graph invocation.

### Dynamic Tools Default Denied

- The `ResearchToolRegistry` enforces a permission policy chain: system admin -> workspace admin -> workspace permission -> tool policy -> default denied.
- Any tool without an explicit permission rule is **denied by default** at registration time, not at call time. This prevents accidental capability exposure when new tools are added.
- **Trade-off**: adding a new research tool requires updating the tool manifest and the security policy. This is intentional: every tool should be explicitly reviewed before it becomes available to LLM planners.

### Delivery Separate from Research Execution

- Research execution and report delivery are independent Taskiq tasks. If delivery fails, the completed report is preserved in PG and can be re-delivered. If research fails, delivery is never enqueued.
- This isolation prevents cascading failures: a transient WeChat API issue during delivery doesn't invalidate an otherwise correct research report.
- **Trade-off**: an additional async hop means the user waits slightly longer for delivery notification. For async research (minutes of LLM time), the extra few seconds are negligible.
