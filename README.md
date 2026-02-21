# Learn Claude Code -- Build an AI Agent From Scratch

```
                    THE AGENT PATTERN
                    =================

    User --> messages[] --> LLM --> response
                                      |
                            stop_reason == "tool_use"?
                           /                          \
                         yes                           no
                          |                             |
                    execute tools                    return text
                    append results
                    loop back -----------------> messages[]


    That's it. Every AI coding agent is this loop.
    Everything else is refinement.
```

**Learn how modern AI agents work by building one from scratch -- 11 progressive sessions, from 70 lines to full autonomous teams.**

> **Disclaimer**: This is an independent educational project. It is not affiliated with, endorsed by, or sponsored by Anthropic. "Claude Code" is a trademark of Anthropic.

---

## Architecture

```
learn-claude-code/
|
|-- agents/                        # Python reference implementations
|   |-- s01_agent_loop.py          #   ~70 LOC: while loop + bash
|   |-- s02_multi_tool.py          #   ~90 LOC: + Read, Write, Edit, Bash
|   |-- s03_structured_planning.py #  ~150 LOC: + TodoWrite
|   |-- s04_context_isolation.py   #  ~130 LOC: + Task tool / subagents
|   |-- s05_knowledge_loading.py   #  ~150 LOC: + SKILL.md injection
|   |-- s06_compression.py         #  ~180 LOC: + /compact (3-layer)
|   |-- s07_file_tasks.py          #  ~170 LOC: + Tasks API + deps
|   |-- s08_background.py          #  ~160 LOC: + background threads
|   |-- s09_team_messaging.py      #  ~340 LOC: + Agent Teams + mailboxes
|   |-- s10_team_protocols.py      #  ~390 LOC: + shutdown + plan approval
|   |-- s11_autonomous.py          #  ~490 LOC: + idle cycle + auto-claim
|   +-- s_full.py                  #  full combined reference
|
|-- web/                           # Interactive learning platform
|   |-- src/agents/                #   TypeScript agent implementations
|   |   |-- s01.ts ... s11.ts      #     run in browser, no sandbox
|   |   +-- shared/                #     base class, API client, VFS
|   |-- src/components/
|   |   |-- inspector/             #   Live state inspector
|   |   |-- simulator/             #   Step-through agent execution
|   |   +-- architecture/          #   Flow diagrams, arch diagrams
|   |-- src/hooks/
|   |   +-- useAgentRunner.ts      #   Runs agent + feeds state
|   +-- src/app/                   #   Next.js pages
|       +-- [locale]/(learn)/
|           |-- [version]/         #     Per-version learning page
|           +-- playground/        #     Live agent playground
|
|-- docs/                          # Mental-model-first documentation
|   |-- s01-the-agent-loop.md      #   11 session docs
|   |-- ...
|   +-- s11-autonomous-agent.md
|
|-- skills/                        # Skill files for s05
+-- .github/workflows/ci.yml      # CI: typecheck + test + build
```

## Learning Path

```
Phase 1: THE LOOP                   Phase 2: PLANNING & KNOWLEDGE
=================                   ==============================
s01: The Agent Loop                 s03: TodoWrite
|  bash is all you need             |  plan before you act
|  "The entire agent is a loop"     |  "Visible plans improve completion"
|                                   |
+-> s02: Tools                      s04: Subagents
    |  Read, Write, Edit, Bash      |  fresh context via Task tool
    |  "The loop didn't change"     |  "Process isolation = context isolation"
                                    |
                                    s05: Skills
                                    |  SKILL.md + tool_result injection
                                    |  "Load on demand, not upfront"
                                    |
                                    s06: Compact
                                       three-layer context compression
                                       "Strategic forgetting"

Phase 3: PERSISTENCE                Phase 4: TEAMS
=================                   =====================
s07: Tasks                          s09: Agent Teams
|  persistent CRUD + dependencies   |  teammates + mailboxes
|  "State survives /compact"        |  "Append to send, drain to read"
|                                   |
s08: Background Tasks               s10: Team Protocols
   fire-and-forget threads + notify |  shutdown + plan approval
   "Fire and forget"                |  "Same request_id, two protocols"
                                    |
                                    s11: Autonomous Agents
                                       idle cycle + auto-claim
                                       "Poll, claim, work, repeat"

Phase 5: THE HARNESS
====================
s12: Structured Handoffs
|  diff + narrative + status + metrics
|  "Show your work, not just results"
|
s13: Scratchpad Rewriting
|  REWRITE not append, auto-summarize
|  "Fresh context, always current"
|
s14: Planner-Worker Split
|  planners delegate, workers execute
|  "Think and do are separate roles"
|
s15: Worker Isolation
|  per-worker workspace copies
|  "Your mess, your sandbox"
|
s16: Optimistic Merge
|  3-way merge + fix-forward
|  "Conflicts are tasks, not blockers"
|
s17: Recursive Hierarchy
|  root → sub-planners → workers
|  "Fractals all the way down"
|
s18: Error Tolerance
|  error budgets, errors-as-tasks
|  "Accept imperfection, fix forward"
|
s19: Failure Modes & Recovery
|  watchdog: zombie/tunnel-vision/burn
|  "Detect and restart, don't debug"
|
s20: Reconciliation Pass
   green branch + fixer loop
   "One final sweep to green"
```

## Quick Start

### Interactive Web Platform (Recommended)

Visit the deployed web app to explore all versions interactively:
- Step-through simulator shows each agent loop iteration
- State inspector reveals internal state in real-time
- Live playground runs real agents in your browser (bring your API key)

### Run Python Agents Locally

```sh
# Clone and install
git clone https://github.com/shareAI-lab/learn-claude-code
cd learn-claude-code

pip install -r requirements.txt

# Configure API key
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Run any session
python agents/s01_agent_loop.py       # Start here
python agents/s11_autonomous.py       # Full autonomous team
```

### Run TypeScript Agents (Web)

```sh
cd web
npm install
npm run dev
# Open http://localhost:3000/en/playground
# Enter your Anthropic API key
# Select a version and chat with the agent
```

## Session Comparison

```
Session  Claude Code Feature   LOC  Tools Core Addition            Key Insight
-------  --------------------  ---  ----- ----------------------   --------------------------
s01      The Agent Loop         70    1   while + stop_reason      Bash is all you need
s02      Tools                  90    4   Read/Write/Edit/Bash     The loop didn't change
s03      TodoWrite             150    5   TodoManager + nag        Plan before you act
s04      Subagents             130    5   Task tool + spawn        Fresh context per subagent
s05      Skills                150    5   SKILL.md injection       Load on demand, not upfront
s06      Compact               180    5   3-layer compression      Strategic forgetting
s07      Tasks                 170    8   CRUD + dependency graph  State survives /compact
s08      Background Tasks      160    6   threads + notifications  Fire and forget
s09      Agent Teams           340   10   teammates + mailboxes   Persistent agents + async mailboxes
s10      Team Protocols        390   12   shutdown + plan approval Same request_id, two protocols
s11      Autonomous Agents     490   14   idle cycle + auto-claim  Poll, claim, work, repeat
s12      Structured Handoffs   751   15   review_handoff           Show your work, not just results
s13      Scratchpad Rewriting 1110   17   scratchpad read/write   Fresh context, always current
s14      Planner-Worker Split  998   18   delegate + execute       Think and do are separate roles
s15      Worker Isolation     1119   16   per-worker workspaces    Your mess, your sandbox
s16      Optimistic Merge     1464   17   3-way merge + fix       Conflicts are tasks, not blockers
s17      Recursive Hierarchy  1303   18   sub-planners            Fractals all the way down
s18      Error Tolerance      882   17   error budgets            Accept imperfection, fix forward
s19      Failure Modes        1648   18   watchdog patterns       Detect and restart, don't debug
s20      Reconciliation Pass  935   16   fixer loop              One final sweep to green
```

## The Core Pattern

```python
# Every AI agent is this loop:
def agent_loop(messages):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM,
            messages=messages, tools=TOOLS,
        )
        messages.append({"role": "assistant",
                         "content": response.content})

        if response.stop_reason != "tool_use":
            return

        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = TOOL_HANDLERS[block.name](**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": results})
```

Each session adds ONE mechanism on top of this loop.

## Key Mechanisms

| Claude Code Feature | Session | What It Does                                    |
|---------------------|---------|-------------------------------------------------|
| Agent loop          | s01     | `while (stop_reason == "tool_use")` loop        |
| Tools               | s02     | Map of tool name -> handler function            |
| TodoWrite           | s03     | Create plan before execution, track completion   |
| Subagents           | s04     | Fresh message list per subagent via Task tool    |
| Skills              | s05     | SKILL.md content injected via tool_result        |
| Compact (micro)     | s06     | Old tool results replaced with placeholders      |
| Compact (auto)      | s06     | LLM summarizes conversation when tokens > limit  |
| Tasks API           | s07     | File-based tasks with dependency graph           |
| Background tasks    | s08     | Threaded commands + notification queue           |
| Agent Teams         | s09     | Named persistent agents with config.json         |
| Mailbox             | s09     | Append-only file-based messages, per-teammate     |
| Shutdown protocol   | s10     | request_id based FSM for graceful shutdown       |
| Plan approval       | s10     | Submit/review with request_id correlation        |
| Idle cycle          | s11     | Poll board, auto-claim unclaimed tasks           |
| Structured handoff | s12     | Diff + narrative + status + metrics submission   |
| Scratchpad         | s13     | Rewrite, not append, auto-summarize context      |
| Planner role       | s14     | Delegate tasks, don't execute them               |
| Worker isolation   | s15     | Per-worker workspace copies in /tmp             |
| Optimistic merge   | s16     | 3-way merge with fix-forward on conflict         |
| Sub-planners       | s17     | Root → sub-planners → workers hierarchy         |
| Error budget       | s18     | Track error counts, fail gracefully             |
| Watchdog           | s19     | Detect zombie/tunnel-vision/burn, restart      |
| Reconciliation     | s20     | Green branch check + fixer loop                |

## State Inspector

The web platform includes a state inspector that shows internal agent state:

```
+---------------------------+-------------------+
|                           |  State Inspector   |
|  Chat / Simulator         |                    |
|                           |  messages[]: 4     |
|  [User] Create hello.py   |  loop: 2          |
|  [Assistant] Creating...  |  tokens: 1,247    |
|  [Tool: bash] echo ...    |  tools: [bash]    |
|  [Result] File written    |  stop: tool_use   |
|                           |                    |
+---------------------------+-------------------+
```

Each session shows session-specific state:
- s03: todo checklist with completion status
- s06: token gauge bar with compression threshold
- s07: task dependency graph with status colors
- s08: background thread timeline
- s09-s11: team roster, inbox viewer, protocol FSM, idle cycle

## Running Tests

```sh
cd web
npx vitest run          # Unit + integration tests
npx tsc --noEmit        # Type check
npm run build           # Full build
```

## Documentation

Each doc follows a mental-model-first structure with ASCII diagrams:

- [s01: The Agent Loop](./docs/s01-the-agent-loop.md)
- [s02: Tools](./docs/s02-multi-tool-dispatch.md)
- [s03: TodoWrite](./docs/s03-structured-planning.md)
- [s04: Subagents](./docs/s04-context-isolation.md)
- [s05: Skills](./docs/s05-knowledge-loading.md)
- [s06: Compact](./docs/s06-context-compression.md)
- [s07: Tasks](./docs/s07-file-based-tasks.md)
- [s08: Background Tasks](./docs/s08-background-execution.md)
- [s09: Agent Teams](./docs/s09-team-messaging.md)
- [s10: Team Protocols](./docs/s10-team-protocols.md)
- [s11: Autonomous Agents](./docs/s11-autonomous-agent.md)

## License

MIT

---

**The model is the agent. Our job is to give it tools and stay out of the way.**
