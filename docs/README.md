# Documentation

```text
docs/
├── guides/          # How to install, configure and run
├── architecture/    # System design: summary page + full design PDF
├── services/        # How each service is built
└── contracts/       # Cross-service contracts (APIs, events, streams)
```

| Folder | Page | What it covers |
| --- | --- | --- |
| `guides/` | [Getting started](guides/getting-started.md) | Install, configure and run the project locally |
| `architecture/` | [Architecture](architecture/README.md) | AI Act Governance Copilot: MVP scope, containers, pipelines, decisions |
| `architecture/` | [Design document (PDF, Greek)](architecture/ai-act-governance-copilot.pdf) | Full system design: personas, layers, agents, HITL gates, data model, eval, MVP |
| `services/` | [Backend: async sub-agents](services/backend.md) | The backend's task mirror, task routes and sockets, channel frames, the wake-up flow and its settings |
| `services/` | [Agents service](services/agents-service.md) | How the agents service is built: run path, filesystem and uploads, tools and approvals, MCP, sandbox, tracing, env vars |
| `contracts/` | [Agents-service contract](contracts/agents-contract.md) | What the agents service must implement for the backend: endpoints, request JSON, AG-UI events, errors |

Put a new page in the folder that matches it and add a row here.
