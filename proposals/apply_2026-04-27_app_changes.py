#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA')
APP = ROOT / 'dashboard' / 'app.py'

def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if new in text:
        print(f'OK already patched: {path}')
        return
    if old not in text:
        raise SystemExit(f'Pattern not found in {path}')
    path.write_text(text.replace(old, new, 1))
    print(f'Patched: {path}')

replace_once(
    APP,
    '''@app.get("/api/stream/stats")
async def api_stream_stats(user: Optional[dict] = Depends(get_current_user)):
    """Diagnostic: current broadcaster state."""
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse(PRICE_BROADCASTER.stats())''',
    '''@app.get("/api/stream/stats")
async def api_stream_stats(user: Optional[dict] = Depends(get_current_user)):
    """Diagnostic: current broadcaster state."""
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse(PRICE_BROADCASTER.stats())

@app.get("/api/signals/hit_stats")
async def api_signals_hit_stats(days: int = 30):
    from analytics import get_signal_hit_stats
    return JSONResponse(get_signal_hit_stats(days))'''
)

print('Done. Recommended verification: python -m py_compile dashboard/app.py')
