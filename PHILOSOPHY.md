# Philosophy

Design principles behind Conclave.

## Agents as Coworkers

Agents should fit into existing human workflows like coworkers — using the same tools, the same chat, the same task board. Conclave is built around the kind of workflow that developers already use: a terminal, a browser, a chat room, and a kanban board. This pattern is well-represented in training data, which helps agents behave naturally within it.

Agents are regular users. Each agent has its own account in Matrix and Planka, receives tasks through the same channels a human would, and reports progress the same way. The agent shares an interactive `dev` user for filesystem access, simplifying working tree permissions and tool configuration.

## Why One Container

Conclave runs everything in a single container for three reasons:

- **Platform support.** GPU pod platforms like Runpod expect one container per pod. Splitting into multiple containers would require orchestration that most GPU platforms don't provide.
- **Latency.** Services communicate over localhost. The browser automation (CDP), database queries, and LLM inference all stay on the same machine with no network hops.
- **Security.** Internal services like CDP (port 9222) bind to localhost only. There's no need to secure inter-service traffic when there is no network between them.

## Persistence

Everything important lives on a single `/workspace` volume mount:

- Browser session and profile
- Skills and extensions
- Agent home directory and configuration
- ChromaDB vector store
- SQLite databases
- PostgreSQL (Matrix + Planka data)
- Agent memory and notes

This means pod restarts, container upgrades, and image rebuilds preserve all state. First boot generates secrets and initializes databases; subsequent boots reuse what's already there.

## Automatic Setup

On first start, Conclave generates unique passwords for every service, initializes databases, creates admin and agent users, sets up a Matrix room and Planka board, and pulls a default LLM. No manual configuration required. Provide an admin password and API keys if you want, or let it generate everything.

## Provider Agnostic

Conclave includes Ollama for local inference — useful for quick tasks, vision, or running entirely offline. For multi-user or high-throughput scenarios, vLLM is a better fit but less compatible for single-user setups. The coding agents support multiple providers (Anthropic, OpenAI, local Ollama) and can switch between them per-task.

## Hardware Flexibility

Conclave scales to any GPU size. Best with 48GB VRAM or more for running capable local models, but it works on smaller GPUs, CPU-only machines, and even APUs or mini PCs. What you can run locally depends on your hardware; the cloud API providers are always available regardless.

## Upstream Without Modifications

All upstream projects are used as-is. No patches to Synapse, Planka, N.eko, Ollama, or any other bundled service. No modifications to Pi's source code — only skills and extensions. This keeps upgrades simple and avoids maintaining forks.

## Multiple Interaction Modes

You can interact with Conclave through the web terminal, SSH, the Matrix chat, or the N.eko browser session — all at the same time, with no loss of context. The agent polls Matrix from its primary tmux session, so messages sent through Element arrive in the same place as terminal commands.

## Persistent Browser

The Chromium session persists across tasks. Agents can leave tabs open and move through websites progressively rather than constantly fetching pages from scratch. This is more responsible internet usage — fewer redundant requests — and helps with stealth, especially with a few browser plugins installed. When the agent hits a captcha, N.eko provides an interactive session for a human to step in.

## Notes and Self-Reflection

Agents take notes as they work, storing context in ChromaDB and local memory files. After a project, the self-reflection skill reviews what happened — identifying issues, gaps in skills, and missing context — so the next session starts from a better baseline.

## No MCP

Conclave does not use MCP internally. No external MCP servers are configured by default either, though you could add them. The preferred interaction model is bash and Python — tools that agents already understand well and that don't require additional protocol layers.

## Security

Security is focused at the perimeter: SSH key-only authentication, nginx basic auth, fail2ban, and hardened SSH settings. Inside the container, the tradeoff is pragmatic — there's no way to secure a browser cookie from Playwright running in the same session, and the agent necessarily has its credentials in the environment. The agent is given the least privilege necessary within each application (regular user, not admin).

If you are focused on security, consider:

- Building your own container image from source
- Serving it from your own private registry
- Keeping all services firewalled, including nginx
- Logging in exclusively through an SSH tunnel or WireGuard
- Using only the local Ollama instance (no external API calls)
- Not using any credentials you care about in the browser or terminal
- Maybe not using this at all
- Just staying off the internet altogether
- Two words: hermit cave
