# Reverse Hunt Signal Logic — Visualized

_Generated: 2026-04-25_

## The state machine (spec — the green path)

```
┌─────────────────────────────────────────────────────────────────┐
│                  REVERSE HUNT STATE MACHINE                      │
└─────────────────────────────────────────────────────────────────┘

         TSI in neutral zone (|TSI| < L1)
                       │
                       ▼
                  ┌──────────┐
                  │   IDLE   │  ◄── starting state
                  └────┬─────┘
                       │  TSI crosses L1 (extreme entry)
                       ▼
                  ┌──────────────┐
                  │  MONITORING  │  TSI in L1 zone (overbought OR oversold)
                  │     (L1)     │  ▶ pair tracked
                  └──────┬───────┘
                         │  TSI deepens past L2
                         ▼
                  ┌──────────────┐
                  │   EXTREME    │  TSI past L2 threshold
                  │     (L2)     │  ▶ continuing to track
                  └──────┬───────┘
                         │  TSI starts pulling back toward L1
                         ▼
                  ┌──────────────┐
                  │  RECOVERING  │  TSI between L1 and L2
                  │              │  ▶ still tracking
                  └──────┬───────┘
                         │  TSI fully exits L1 (back to neutral)
                         ▼
                  ┌──────────────┐
                  │    ARMED     │  RH grants CE permission ✓
                  │              │  Waiting for CE Hybrid flip
                  └──────┬───────┘
                         │
                         │  CE Line flips matching direction
                         ▼
              ┌───────────────────────┐
              │  🟢 PRODUCTION SIGNAL │  zone_used = OS_L2_ARMED
              │   ✓ Public Telegram   │              or OB_L2_ARMED
              │   ✓ Copy-trade        │
              │   ✓ Public dashboard  │
              └───────────────────────┘
```

---

## The 6 bypass paths (experimental tier — red dashed)

```
                      IDLE
                       │
                       ▼
       ┌──────────────────────────────────┐
       │ ⚠️  PATH 1: IDLE→EXTREME jump    │   TSI gaps neutral→L2 in 1 bar
       │     skips MONITORING             │   (state-machine acceleration —
       │                                  │   stays inside ARMED path,        ✅ tagged production
       │                                  │   ends at OS_L2_ARMED)
       └──────────────────────────────────┘

                    EXTREME
                       │
       ┌───────────────┼───────────────┐
       │               │               │
       ▼               ▼               ▼
  ┌─────────┐   ┌─────────────┐   ┌──────────────┐
  │ ⚠️  P2  │   │ ⚠️  P4      │   │ ⚠️  P5       │
  │ EXTREME │   │ PROLONGED   │   │ EXTREME_MODE │
  │ →ARMED  │   │ ─ in L2 ≥ N │   │ V-bottom     │
  │ skip    │   │ bars + CE   │   │ in L2 + vol  │
  │ RECOVER │   │ flip while  │   │ surge + CE   │
  │ (1 bar) │   │ STILL in L2 │   │ flip in L2   │
  │ ✅ stays│   │ ❌ FIRES    │   │ ❌ FIRES     │
  │   prod  │   │   from L2   │   │   from L2    │
  └─────────┘   └──────┬──────┘   └──────┬───────┘
                       │                 │
                       ▼                 ▼
                   🧪 LAB             🧪 LAB
                   experimental       experimental
                   PROLONGED_OS/OB    EXTREME_OS_L2/OB_L2

                    ARMED (fresh)
                       │
                       ▼
              ┌─────────────────────┐
              │ ⚠️  P3: ARMED_IMM   │   On entering ARMED, looks BACK
              │   retroactive CE    │   N bars: if CE already flipped
              │                     │   before arming, fires immediately
              │   ❌ CE flip was    │
              │   BEFORE arming     │
              └──────────┬──────────┘
                         │
                         ▼
                     🧪 LAB
                     experimental
                     OS_L2_ARMED_IMM / OB_L2_ARMED_IMM

                    ANY STATE
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
  ┌─────────────────┐         ┌──────────────────┐
  │ ❌ P6: CE_      │         │ ❌ P7: PERSISTENT│
  │ MOMENTUM        │         │ fallback in      │
  │                 │         │ process_pair()   │
  │ TSI may be in   │         │ when main loop   │
  │ NEUTRAL         │         │ returned no      │
  │ entire time     │         │ signal but TSI   │
  │ Pure CE breakout│         │ is in L2 + CE up │
  │ + momentum      │         │                  │
  └────────┬────────┘         └────────┬─────────┘
           │                           │
           ▼                           ▼
       🧪 LAB                       🧪 LAB
       experimental                 experimental
       CE_MOMENTUM_LONG/SHORT       PERSISTENT_OS_L2/OB_L2
       (← TON/USDT 2026-04-23       (← all 21 backfilled
        −6.35% example)              historicals were this)
```

---

## Tier routing (deployed 2026-04-25)

```
┌─────────────────────────────────────────────────────────────────┐
│                   FIRE-PATH TIER ROUTING                         │
└─────────────────────────────────────────────────────────────────┘

  RH simulation produces zone_used tag
                  │
                  ▼
        ┌─────────────────────┐
        │ _classify_signal_   │
        │   tier(zone_used)   │
        └──────────┬──────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
  zone in {OS_L2_ARMED,    everything else
   OB_L2_ARMED,             (the 6 paths above)
   TV_SIGNAL}                      │
        │                          │
        ▼                          ▼
  ┌──────────────┐          ┌──────────────┐
  │  PRODUCTION  │          │ EXPERIMENTAL │
  └──────┬───────┘          └──────┬───────┘
         │                         │
         ├─ ✅ Public Telegram     ├─ ❌ NO Telegram
         ├─ ✅ Copy-trade          ├─ ❌ NO copy-trade
         ├─ ✅ Public dashboard    ├─ ❌ NO public dashboard
         ├─ ✅ Cycle-cap counted   └─ ✅ Admin "🔬 Lab" tab only
         └─ ✅ Daily count
```

---

## One-line summary

> **Production = the clean state-machine path (IDLE → MONITORING → EXTREME → RECOVERING → ARMED → CE flip).**
>
> **Experimental = the 6 shortcuts the engine takes when it's "impatient."**
>
> The spec-compliant path is the only one that reaches subscribers. Shortcuts
> still fire — they live in the Lab tab for win-rate analysis and possible
> future promotion based on evidence.

---

## Code references

- State machine: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/reverse_hunt.py`
- Tier classifier: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.py:110-134`
- Production zones: `_PRODUCTION_ZONES = {'OS_L2_ARMED', 'OB_L2_ARMED', 'TV_SIGNAL'}`
- Tier branching at fire time: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/main.py:930-968`
- Public-surface filtering (SQL): all `signal_tier='production'` filters in `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py`
- Lab API: `GET /api/admin/lab/signals` in `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/app.py:1430-1527`
- Lab UI: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/dashboard/static/js/lab.js`
- Backfill script: `@/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/scripts/backfill_lab_signals.py`
