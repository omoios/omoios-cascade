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
|   |-- s02_multi_tool.py          #   ~90 LOC: + multi-tool dispatch
|   |-- s03_structured_planning.py #  ~150 LOC: + TodoManager
|   |-- s04_context_isolation.py   #  ~130 LOC: + subagent spawn
|   |-- s05_knowledge_loading.py   #  ~150 LOC: + skill injection
|   |-- s06_compression.py         #  ~180 LOC: + three-layer compress
|   |-- s07_file_tasks.py          #  ~170 LOC: + task CRUD + deps
|   |-- s08_background.py          #  ~160 LOC: + background threads
|   |-- s09_team_messaging.py      #  ~340 LOC: + team + JSONL inboxes
|   |-- s10_team_protocols.py      #  ~390 LOC: + shutdown + plan approval
|   |-- s11_autonomous.py          #  ~490 LOC: + idle cycle + claim
|   +-- s_full.py                  #  full combined reference
|
|-- web/                           # Interactive learning platform
|   |-- src/agents/                #   TypeScript agent implementations
|   |   |-- v0.ts ... v9.ts        #     run in browser, no sandbox
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
=================                   ==========================
s01: Agent Loop                     s03: Structured Planning
|  while + bash                     |  TodoManager + nag reminder
|  "The entire agent is a loop"     |  "Make plans visible"
|                                   |
+-> s02: Multi-Tool Dispatch        s04: Context Isolation
    |  dispatch map routing         |  subagent with fresh messages
    |  "The loop didn't change"     |  "Process isolation = context isolation"
                                    |
                                    s05: Knowledge Loading
                                    |  SKILL.md + two-layer injection
                                    |  "Load on demand, not upfront"
                                    |
                                    s06: Context Compression
                                       three-layer compression pipeline
                                       "Strategic forgetting"

Phase 3: PERSISTENCE                Phase 4: TEAMS
=================                   =====================
s07: File-Based Tasks               s09: Team Messaging
|  TaskManager + dependency graph   |  TeammateManager + JSONL inboxes
|  "State survives compression"     |  "Teammates that communicate"
|                                   |
s08: Background Execution           s10: Team Protocols
   BackgroundManager + threads      |  shutdown + plan approval handshake
   "Fire and forget"                |  "Same request_id, two applications"
                                    |
                                    s11: Autonomous Agent
                                       idle cycle + task board polling
                                       "The agent finds work itself"
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
Session  Title                 LOC  Tools Core Addition           Key Insight
-------  --------------------  ---  ----- ---------------------   --------------------------
s01      Agent Loop             70    1   while + bash            The entire agent is a loop
s02      Multi-Tool Dispatch    90    4   dispatch map            The loop didn't change
s03      Structured Planning   150    5   TodoManager + nag       Make plans visible
s04      Context Isolation     130    5   run_subagent()          Process isolation
s05      Knowledge Loading     150    5   SkillLoader 2-layer     Load on demand
s06      Context Compression   180    5   3-layer compress        Strategic forgetting
s07      File-Based Tasks      170    8   TaskManager + deps      State survives compression
s08      Background Execution  160    6   BackgroundManager       Fire and forget
s09      Team Messaging        340    9   Teammates + JSONL inbox Teammates that communicate
s10      Team Protocols        390   12   shutdown + plan approval Same pattern, two domains
s11      Autonomous Agent      490   14   idle cycle + claim      Self-organizing teams
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

| Mechanism            | Session | What It Does                                    |
|----------------------|---------|-------------------------------------------------|
| Agent loop           | s01     | `while (stop_reason == "tool_use")` loop        |
| Tool dispatch        | s02     | Map of tool name -> handler function            |
| Todo planning        | s03     | Create plan before execution, track completion   |
| Context isolation    | s04     | Fresh message list per subagent                  |
| Skill injection      | s05     | SKILL.md content injected via tool_result        |
| Micro-compact        | s06     | Old tool results replaced with placeholders      |
| Auto-compact         | s06     | LLM summarizes conversation when tokens > limit  |
| Task CRUD + deps     | s07     | File-based tasks with dependency graph           |
| Background execution | s08     | Threaded commands + notification queue           |
| Teammate lifecycle   | s09     | Named persistent agents with config.json         |
| File-based inbox     | s09     | JSONL messages, 5 types, per-teammate files      |
| Shutdown protocol    | s10     | request_id based FSM for graceful shutdown       |
| Plan approval        | s10     | Submit/review with request_id correlation        |
| Idle cycle           | s11     | Poll board, auto-claim unclaimed tasks           |

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
- [s02: Multi-Tool Dispatch](./docs/s02-multi-tool-dispatch.md)
- [s03: Structured Planning](./docs/s03-structured-planning.md)
- [s04: Context Isolation](./docs/s04-context-isolation.md)
- [s05: Knowledge Loading](./docs/s05-knowledge-loading.md)
- [s06: Context Compression](./docs/s06-context-compression.md)
- [s07: File-Based Tasks](./docs/s07-file-based-tasks.md)
- [s08: Background Execution](./docs/s08-background-execution.md)
- [s09: Team Messaging](./docs/s09-team-messaging.md)
- [s10: Team Protocols](./docs/s10-team-protocols.md)
- [s11: Autonomous Agent](./docs/s11-autonomous-agent.md)

## License

MIT

---

**The model is the agent. Our job is to give it tools and stay out of the way.**
