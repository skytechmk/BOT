import asyncio
import json
import logging
import os
import shutil

logger = logging.getLogger("Aladdin")

# Resolve the OpenClaw binary — NVM installs it under a versioned path
_OPENCLAW_BIN = shutil.which("openclaw") or "/root/.nvm/versions/node/v24.14.1/bin/openclaw"
_BOT_DIR = "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA"


def _escape_prompt(prompt: str) -> str:
    """Sanitize prompt for safe shell embedding."""
    return prompt.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')


def _extract_reply(raw: str) -> str:
    """Extract the agent reply text from OpenClaw JSON or raw output."""
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            for key in ('reply', 'output', 'message', 'content', 'text'):
                if key in result:
                    return str(result[key])
            choices = result.get('choices')
            if choices and isinstance(choices, list):
                msg = choices[0].get('message', {})
                if 'content' in msg:
                    return msg['content']
        return raw
    except (json.JSONDecodeError, KeyError, IndexError):
        return raw


async def ask_openclaw(prompt: str, timeout: float = 90.0) -> str:
    """
    Query the OpenClaw agent via local CLI.
    
    API keys and model fallbacks are configured in openclaw.json —
    no env var loading or SSH fallback needed.
    """
    safe = _escape_prompt(prompt)
    cmd = f'{_OPENCLAW_BIN} agent --agent main --local --message "{safe}" --json'
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_BOT_DIR
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        return "⚠️ OpenClaw agent timed out. Please try again."

    if process.returncode == 0:
        reply = _extract_reply(stdout.decode().strip())
        if reply and len(reply.strip()) > 5:
            logger.info(f"OpenClaw responded ({len(reply)} chars)")
            return reply
        return "⚠️ OpenClaw returned an empty response."
    else:
        err = stderr.decode().strip() or f"exit code {process.returncode}"
        logger.error(f"OpenClaw CLI failed: {err}")
        return f"⚠️ OpenClaw error: {err}"
