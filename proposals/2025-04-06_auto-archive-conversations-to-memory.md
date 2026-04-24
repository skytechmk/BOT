# Proposal: Automatic Conversation Archiving to memory/

**Date**: 2025-04-06  
**Priority**: LOW  
**Files affected**: `telegram_handler.py`

---

## Problem

Manual cron‑based archiving fails because the bot’s polling **consumes updates**; a separate script using `getUpdates` sees nothing new. We need real‑time capture.

---

## Solution

Hook into the Telegram message handler and append every custom command + channel post to a daily memory file (`memory/YYYY-MM-DD.md`). This gives you daily conversation archives automatically, no cron required.

---

## Implementation

In `telegram_handler.py`, add a helper:

```python
def append_to_daily_memory(chat_label: str, sender: str, text: str, ts: float):
    """Append a message to memory/YYYY-MM-DD.md."""
    from datetime import datetime, timezone
    path = BASE / 'memory' / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
    path.parent.mkdir(exist_ok=True)
    dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M UTC')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"[{dt_str}] <{sender}> {text.strip()}\n")
```

Then, inside the channel post handler (`handle_channel_post` or wherever `process_cornix_response` is called), add after processing:

```python
# Archive to memory (if you want to store all channel posts, not just Cornix)
sender_name = update.effective_chat.username or str(update.effective_chat.id)
append_to_daily_memory(
    chat_label="ANUNNAKI_OPS",
    sender=sender_name,
    text=text,
    ts=update.effective_message.date
)
```

If you only want to archive messages **from this Ops group** (not all chats), check `chat_id == OPS_TELEGRAM_CHAT_ID` first.

---

## Notes

- Files in `memory/` are append‑only daily logs; keep them compressed after a month if needed.
- `MEMORY.md` index remains untouched; `memory_search` / `memory_get` already read from `memory/*.md`.
- No performance impact — file append is cheap and async handled by the existing event loop.

---

## Rollback

Comment out the `append_to_daily_memory` call and reload bot.

---

## Acceptance

- New daily files appear in `memory/` with `[HH:MM UTC] <sender> message`
- `memory_get` can retrieve past days' conversations
- No interference with signal parsing
