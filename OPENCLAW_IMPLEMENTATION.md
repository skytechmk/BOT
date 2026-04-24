# OpenClaw Multi-Agent Bridge Implementation

This document serves as a hand-off for the integration between **S.P.E.C.T.R.E.** and the **OpenClaw** agentic framework.

## Current Architecture
- **Host**: S.P.E.C.T.R.E. Trading Bot (Local)
- **Node**: OpenClaw Gateway/Agent Node (`10.10.10.101`)
- **Bridge**: `openclaw_bridge.py` in S.P.E.C.T.R.E. root.
- **Communication**: SSH-based command relay using `sshpass` for zero-configuration asynchronous prompts.

## Configuration Details
### Node (10.10.10.101)
- **User**: `root` | **Password**: `jarvis`
- **OpenClaw Home**: `/root/.openclaw`
- **Primary Provider**: OpenRouter (`api: openai-responses`)
- **Primary Model**: `openrouter/qwen/qwen-2-7b-instruct:free` (Currently transitioning to 70B+ models).
- **Local Fallback**: Ollama is installed and configured as a secondary provider.

### S.P.E.C.T.R.E. Side
- **Bridge File**: `openclaw_bridge.py`
- **Command**: `openclaw agent --agent main --local --message "<prompt>" --json`
- **Note**: The `--local` flag is critical. It forces the remote node to use its local `openclaw.json` configuration rather than trying to sync sessions with the central gateway, which prevents "No API key found" errors caused by session poisoning.

## Planned Work (Next Steps)
1.  **High-Performance Model Upgrade**:
    -   Switch the default model to **`meta-llama/llama-3.1-405b`** or **`deepseek/deepseek-v3`**.
    -   Ensure the OpenRouter API key on the node has sufficient credits (or use `:free` variants).
2.  **Logic Failover**:
    -   Implement a fallback array in `openclaw.json` on the node.
    -   Sequence: `OpenRouter (405B) -> OpenRouter (70B) -> Ollama (Local 14B/27B)`.
3.  **Bridge Enhancement**:
    -   Update `ask_openclaw` to support multi-message streaming or longer timeouts (currently 80s).
    -   Improved JSON parsing for tool-use responses from OpenClaw.

## Critical Files
- `openclaw_bridge.py`: The entry point for all S.P.E.C.T.R.E. -> OpenClaw queries.
- `telegram_handler.py`: Intercepts rate limits and routes to `/claw` command.
- `~/.openclaw/openclaw.json` (on `.101`): The master config for model providers.

## How to Test
Execute in the S.P.E.C.T.R.E. terminal:
```bash
python3 -c "import asyncio; from openclaw_bridge import ask_openclaw; print(asyncio.run(ask_openclaw('Test cloud bridge')))"
```
Or via Telegram: `/claw <prompt>`
