#!/usr/bin/env python3
from pathlib import Path
APP = Path('/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py')
needle = "@app.get(\"/api/signals/hit_stats\")"
insert_after = "def api_signals_hit_stats"
new_code = '''\n\n@app.get("/api/signals/stats")\nasync def api_signals_stats():\n    """Return high-level KPI counts for all signals."""\n    import sqlite3, time\n    DB = Path(__file__).resolve().parent.parent / "signal_registry.db"\n    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)\n    cur = conn.cursor()\n    total = cur.execute("SELECT COUNT(*) FROM signals").fetchone()[0]\n    open_cnt = cur.execute("SELECT COUNT(*) FROM signals WHERE upper(status) IN ('SENT','OPEN','ACTIVE','TP1_HIT','TP2_HIT')").fetchone()[0]\n    closed_cnt = total - open_cnt\n    cutoff = time.time() - 30*86400\n    last30 = cur.execute("SELECT COUNT(*) FROM signals WHERE timestamp>?", (cutoff,)).fetchone()[0]\n    conn.close()\n    return {\n        "total_signals": total,\n        "open_signals": open_cnt,\n        "closed_signals": closed_cnt,\n        "signals_last_30d": last30,\n    }\n'''
text = APP.read_text()
if new_code.strip() in text:
    print('Endpoint already present')
else:
    idx = text.find(needle)
    if idx == -1:
        raise SystemExit('needle not found')
    # find end of that earlier function (next two blank lines?)
    insert_pos = text.find('\n', idx)
    insert_pos = text.find('\n', insert_pos+1)
    patched = text[:insert_pos] + new_code + text[insert_pos:]
    APP.write_text(patched)
    print('Inserted stats endpoint')
