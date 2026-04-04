import asyncio
import time
import os
import sys
from datetime import datetime, timezone
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

# Strategic & Shared State
from constants import *
from shared_state import *
from ai_auto_healer import exception_handler

# Set the global exception hook for self-healing
sys.excepthook = exception_handler

# Modular Components
from utils_logger import log_message, clear_console
from technical_indicators import *
from ml_training import *
from signal_generator import *
from data_fetcher import *
from performance_tracker import *
from signal_cache_manager import *
from telegram_handler import (
    send_telegram_message, send_closed_signal_message, send_ops_message,
    register_signal, generate_signal_id,
    load_signal_registry, load_cornix_signals,
    setup_telegram_listener
)
from trading_utilities import (
    is_prime_trading_session, check_btc_correlation, 
    detect_market_regime
)
from data_fetcher import analyze_funding_rate_sentiment, get_open_interest_change

# Availability Flags are now managed in shared_state.py
realtime_monitor = None

async def process_pair(pair, recommendations_cache, timeframe='15m'):
    """Institutional-grade orchestration for a single pair"""
    try:
        # 0. Yield control to event loop at start
        await asyncio.sleep(0.01)
        
        # PROPOSAL 2+3: HTF Direction + LTF Entry (Multi-Timeframe Confirmation)
        # Step A: Fetch Higher Timeframe (4h) for trend direction
        df_htf = await asyncio.to_thread(fetch_data, pair, PRIMARY_TIMEFRAME)
        if df_htf.empty or len(df_htf) < 50: return
        
        df_htf = await asyncio.to_thread(calculate_kicko_indicator, df_htf, pair, False)
        htf_signal = df_htf['Signal'].iloc[-1].upper() if 'Signal' in df_htf.columns else 'NEUTRAL'
        
        if htf_signal == 'NEUTRAL':
            return  # No trade if 4h trend is unclear
        
        # Step B: Fetch Lower Timeframe (15m) for entry precision
        df = await asyncio.to_thread(fetch_data, pair, timeframe)
        if df.empty or len(df) < 100: return
        
        # 2. Indicator & Signal Calculation (with ML on LTF)
        df = await asyncio.to_thread(calculate_kicko_indicator, df, pair)
        
        current_price = float(df['close'].iloc[-1])
        precision = await asyncio.to_thread(get_precision, pair)
        
        # 2.5 Order Book Depth Analysis
        ob_depth = await asyncio.to_thread(get_order_book_depth, pair)
        imbalance = ob_depth.get('imbalance', 1.0)
        log_message(f"📊 Order Book Alpha for {pair}: Imbalance {imbalance:.2f} (B/A Ratio)")
        
        # 3. Decision Logic & Strategic Gates
        risk_level = MACRO_RISK_ENGINE.update_risk_metrics(client)
        if not MACRO_RISK_ENGINE.should_allow_trading()[0]: return
        
        # Core Filters
        can_trade_cb, _ = CIRCUIT_BREAKER.should_block_trade()
        if can_trade_cb: return
        
        can_trade_bl, _ = AUTO_BLACKLIST.is_blacklisted(pair)
        if can_trade_bl: return
        
        can_trade_cd, _ = PAIR_COOLDOWN.can_send_signal(pair)
        if not can_trade_cd: return
        
        # 4. Signal Analysis
        final_signal = df['Signal'].iloc[-1]
        if final_signal.upper() == 'NEUTRAL': 
            log_message(f"⚪ No Trade: Signal for {pair} is {final_signal}. Silence is golden.")
            return
        
        # PROPOSAL 3: Reject if LTF disagrees with HTF direction
        if final_signal.upper() != htf_signal:
            log_message(f"⚪ No Trade: {pair} HTF={htf_signal} vs LTF={final_signal.upper()} — Timeframe disagreement.")
            return
        
        # ML Confirmation
        ml_confidence = abs(df['Signal_Score'].iloc[-1]) / 8.0
        if MULTI_TF_ML_AVAILABLE:
            ml_pred = get_multi_timeframe_prediction(pair)
            if ml_pred and 'consensus' in ml_pred and ml_pred['consensus']:
                consensus = ml_pred['consensus']
                ml_signal_normalized = 'LONG' if consensus['signal'] == 'BUY' else 'SHORT'
                if ml_signal_normalized == final_signal.upper():
                    ml_confidence = (ml_confidence + consensus['confidence']) / 2
                else:
                    ml_confidence *= 0.5 # Penalize disagreement
        
        # Strategic Overlays
        regime = detect_market_regime(df)
        btc_match, pearson_corr = check_btc_correlation(client, final_signal, pair)
        if not btc_match: ml_confidence *= 0.85
        if not is_prime_trading_session(): ml_confidence *= 0.90
        
        # Institutional Portfolio Correlation Check (Phase 8 Precision)
        is_corr_blocked, corr_reason = PORTFOLIO_MANAGER.get_correlation_risk(pair, OPEN_SIGNALS_TRACKER, btc_correlation=pearson_corr)
        if is_corr_blocked:
            log_message(f"🚫 Signal Rejected for {pair}: {corr_reason}")
            return

        # Funding Rate Sentiment Integration (was dead code — now wired)
        funding_analysis = await asyncio.to_thread(analyze_funding_rate_sentiment, pair)
        funding_bias = funding_analysis.get('signal_bias', 'NONE')
        # FIX 3.2: Use startswith to catch SLIGHT_SHORT/SLIGHT_LONG values
        if funding_bias.startswith('SHORT') and final_signal.upper() == 'LONG':
            ml_confidence *= 0.85  # Overcrowded longs, penalize LONG
        elif funding_bias.startswith('LONG') and final_signal.upper() == 'SHORT':
            ml_confidence *= 0.85  # Overcrowded shorts, penalize SHORT
        elif final_signal.upper() in funding_bias:
            ml_confidence *= 1.05  # Funding agrees with direction
        
        # Clamp confidence to prevent exceeding 1.0 after multipliers
        ml_confidence = min(1.0, ml_confidence)

        # Order Book Imbalance Filter
        if final_signal.upper() == 'LONG' and imbalance < 0.5: ml_confidence *= 0.85  # Heavy sell pressure
        if final_signal.upper() == 'SHORT' and imbalance > 2.0: ml_confidence *= 0.85  # Heavy buy pressure
        
        # PROPOSAL 4: Open Interest Flow Filter
        oi_data = await asyncio.to_thread(get_open_interest_change, pair)
        oi_change = oi_data.get('oi_change', 0.0)
        # Price up + OI down = weak/unsustainable rally → penalize LONG
        if oi_change < -0.03 and final_signal.upper() == 'LONG':
            log_message(f"⚠️ OI declining ({oi_change:+.2%}) during LONG signal for {pair} — penalizing confidence")
            ml_confidence *= 0.85
        # Price down + OI down = weak dump / short covering → penalize SHORT
        elif oi_change < -0.03 and final_signal.upper() == 'SHORT':
            log_message(f"⚠️ OI declining ({oi_change:+.2%}) during SHORT signal for {pair} — penalizing confidence")
            ml_confidence *= 0.85
        # OI rising = genuine participation → boost
        elif oi_change > 0.03:
            ml_confidence *= 1.05
        # 5. Risk Engines & Liquidity Mapping (Phase 8)
        regime = detect_market_regime(df)
        vp_data = await asyncio.to_thread(calculate_volume_profile, df)
        fvg_data = await asyncio.to_thread(calculate_fair_value_gaps, df)
        
        targets, stop_loss = calculate_technical_targets(df, current_price, final_signal, precision, vp=vp_data, fvg_data=fvg_data)
        atr_pct = (df['ATR'].iloc[-1] / current_price) if 'ATR' in df.columns else 0.02
        
        # BUG-2 FIX: Guard against degenerate targets (all targets ≈ entry price)
        if all(abs(t - current_price) / current_price < 0.001 for t in targets):
            log_message(f"🚫 Signal Rejected for {pair}: Degenerate targets (too close to entry)")
            return
        
        # Systemic Fragility Gates
        stress_res = STRESS_TESTER.run_stress_test(OPEN_SIGNALS_TRACKER)
        if stress_res['potential_drawdown_risk'] > 0.35: 
            log_message(f"🚫 Signal Rejected for {pair}: Portfolio Stress too high ({stress_res['potential_drawdown_risk']:.1%})")
            return

        mc_drift = (ml_confidence - 0.35) * (0.05 if final_signal.upper() in ['LONG', 'BUY'] else -0.05)
        mc_results = MONTE_CARLO.simulate_signal(current_price, stop_loss, [(t, 0.2) for t in targets], atr_pct, drift=mc_drift)
        if mc_results['ev'] < 1.0: 
            log_message(f"🚫 Signal Rejected for {pair}: Low EV ({mc_results['ev']:.2f} EV, {mc_results['pos']:.1%} PoS)")
            return
        
        # 5.5 Advanced AI Robustness Filter (DeepSeek Gate)
        deepseek_verdict = 'PROCEED'
        ai_sentiment = {}
        
        if ml_confidence > 0.7:
            # Build detailed technical context for AI reasoning
            latest = df.iloc[-1]
            tech_summary = (
                f"- Signal: {final_signal} (Confidence: {ml_confidence:.2%})\n"
                f"- Price: {current_price:.6f}\n"
                f"- Monte Carlo PoS: {mc_results['pos']:.1%}, EV: {mc_results['ev']:.2f}\n"
                f"- RSI(14): {latest.get('RSI_14', 0):.2f}, RSI(21): {latest.get('RSI_21', 0):.2f}\n"
                f"- MACD Hist: {latest.get('MACD Histogram', 0):.6f}\n"
                f"- Chandelier Direction: {'LONG' if latest.get('CE_Direction', 0) == 1 else 'SHORT' if latest.get('CE_Direction', 0) == -1 else 'N/A'}\n"
                f"- Volume Profile: POC={vp_data.get('poc', 0):.6f}, VAH={vp_data.get('vah', 0):.6f}, VAL={vp_data.get('val', 0):.6f}\n"
                f"- FVG Status: {len(fvg_data.get('unfilled_fvgs', []))} unfilled voids detected."
            )
            
            ds_result = DEEPSEEK_INTEL.analyze_signal_robustness(pair, tech_summary)
            deepseek_verdict = ds_result.get('institutional_verdict', 'PROCEED')
            ai_sentiment = ds_result  
            
            if deepseek_verdict == 'REJECT': 
                reason = ds_result.get('institutional_reasoning', 'Potential liquidity trap detected.')
                warn = ds_result.get('contrarian_warning', 'High fragility.')
                log_message(f"🚫 Signal Rejected for {pair}: AI Analysis Reject - {reason}")
                
                # Telegram notifications for AI Guardrail disabled
                return

        # 6. Signal Execution & Registration
        can_send_lim, remaining = check_daily_signal_limit()
        if not can_send_lim: 
            log_message(f"🚫 Signal Rejected for {pair}: Daily Signal Limit Reached")
            return
            
        can_dir = can_send_direction(pair, final_signal)
        if not can_dir:
            log_message(f"🚫 Signal Rejected for {pair}: Direction already sent recently")
            return
        
        signal_id = generate_signal_id()
        adj_confidence = adaptive_confidence_adjustment(pair, final_signal, ml_confidence)
        
        if adj_confidence < 0.40:
            log_message(f"🚫 Signal Rejected for {pair}: Confidence too low ({adj_confidence*100:.1f}%)")
            return
        
        # Dynamic Confidence Threshold (was dead code — now wired)
        daily_count = DAILY_SIGNAL_COUNTER.get('count', 0)
        dyn_ok, dyn_reason = DYNAMIC_THRESHOLD.should_send(daily_count, adj_confidence)
        if not dyn_ok:
            log_message(f"🚫 Signal Rejected for {pair}: {dyn_reason}")
            return
        
        # Position Sizing (Enhanced with AI Sentiment & Performance)
        regime_mult = REGIME_SIZER.calculate_multiplier(risk_level, ai_sentiment)
        base_size = 25 if adj_confidence < 0.6 else 50 if adj_confidence < 0.8 else 100
        final_size = int(base_size * regime_mult)
        
        # Leverage Calculation (Dynamic Volatility-Based - Phase 8)
        # Maintain constant dollar-risk at SL (Targeting 20% max loss per position size)
        price_at_sl_pct = abs(current_price - stop_loss) / current_price
        if price_at_sl_pct > 0:
            ideal_leverage = 0.20 / price_at_sl_pct
            leverage_val = int(max(5, min(50, ideal_leverage)))
        else:
            leverage_val = 20 # Fallback
        
        # Format targets and SL
        fmt_targets = "\n".join([f"📈 **TP{i+1}:** `{t:.{precision}f}`" for i, t in enumerate(targets)])
        fmt_sl = f"`{stop_loss:.{precision}f}`"
        
        msg = (f"{'🚀' if final_signal.upper() in ['LONG', 'BUY'] else '📉'} **NEW {final_signal.upper()} SIGNAL**\n"
               f"🆔 `{signal_id}` | 💰 **Pair: {pair}**\n"
               f"🎯 Conviction: {adj_confidence*100:.1f}% | ⚙️ Leverage: x{leverage_val}\n"
               f"💼 Sizing: {final_size}% | 🏛️ Regime: {regime}\n"
               f"💵 Entry: `{current_price:.{precision}f}`\n\n"
               f"📈 **Targets:**\n{fmt_targets}\n"
               f"🛑 **SL:** {fmt_sl}\n\n"
               f"🏛️ **ALADDIN INSIGHTS**\n"
               f"🎲 MC PoS: {mc_results['pos']:.1%} | 🧠 AI-Analysis: {deepseek_verdict}\n"
               f"📊 24h Correlation: {pearson_corr:.2f}")
        
        msg_id = await send_telegram_message(msg)
        
        # Post-send Housekeeping
        increment_daily_signal_count()
        PAIR_COOLDOWN.record_signal(pair)  # P0 Fix: was never called, cooldown was broken
        
        # Capture features for learning
        feature_snapshot = df.iloc[-1].to_dict()
        # Remove massive strings/objects to keep registry clean
        feature_snapshot = {k: v for k, v in feature_snapshot.items() if isinstance(v, (int, float, bool, str)) and len(str(v)) < 100}

        register_signal(signal_id, pair, final_signal, current_price, adj_confidence, targets, stop_loss, leverage_val, features=feature_snapshot, telegram_message_id=msg_id)

        add_open_signal(signal_id, pair, final_signal, current_price)
        
        if WEBSOCKET_MONITOR_AVAILABLE and realtime_monitor:
            await realtime_monitor.add_pair_monitoring(pair, {'id': signal_id, 'sl': stop_loss, 'tp': targets})
            
    except Exception as e:
        log_message(f"Error in process_pair for {pair}: {e}")

async def emergency_de_risk(severity="HIGH"):
    """Emergency de-risking during systemic stress events"""
    log_message(f"🚨 EMERGENCY DE-RISK ACTIVATED: Severity {severity}")
    
    msg = (
        f"⚠️ **EMERGENCY DE-RISK: {severity}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ Systemic risk detected. Pausing new signals.\n"
        f"📊 Review open positions for closure.\n"
        f"⏱️ Auto-resume when conditions normalize."
    )
    await send_ops_message(msg)
    
    # Signal global risk state
    MACRO_RISK_ENGINE.state['market_regime'] = 'SYSTEMIC_PANIC'
    MACRO_RISK_ENGINE.save_state()

async def main_async():
    """Central Automation Engine"""
    clear_console()
    log_message("Initializing Aladdin Modular Architecture...")
    
    # 1. Boot up modules
    load_signal_registry()
    load_cornix_signals()
    load_performance_data()
    load_open_signals_tracker()
    initialize_cache_system()
    
    # Note: Telegram Listener has been decoupled to telegram_service.py
    
    global realtime_monitor
    if WEBSOCKET_MONITOR_AVAILABLE:
        realtime_monitor = RealTimeSignalMonitor(
            send_telegram_message, 
            send_closed_signal_message, 
            OPEN_SIGNALS_TRACKER, 
            SIGNAL_REGISTRY
        )
        await realtime_monitor.initialize(API_KEY, API_SECRET)
        await realtime_monitor.start_monitoring()

    log_message("System Online. Starting Market Surveillance...")
    
    last_status_report = time.time()
    last_phase7_check = time.time()
    
    # Concurrency primitives (moved outside loop to prevent per-cycle recreation)
    semaphore = asyncio.Semaphore(5)
    
    async def semaphore_process(p):
        async with semaphore:
            try:
                await process_pair(p, {})
            except Exception as e:
                log_message(f"Error in parallel processing of {p}: {e}")
    
    while True:
        try:
            cycle_start = time.time()
            current_time = time.time()
            
            # Phase 7: Black Swan Surveillance (Every 30m)
            if current_time - last_phase7_check >= 1800:
                log_message("🔎 Running Systemic Fragility & Stress Tests...")
                stress_res = STRESS_TESTER.run_stress_test(OPEN_SIGNALS_TRACKER, scenario="SYSTEMIC_PANIC")
                
                # AI Surveillance
                fragility = OPENROUTER_INTEL.analyze_systemic_fragility("Recent market trends and high-volatility events")
                
                if stress_res['severity'] == 'CRITICAL' or fragility.get('severity') == 'CRITICAL':
                    await emergency_de_risk(severity="CRITICAL")
                elif stress_res['severity'] == 'HIGH' or fragility.get('severity') == 'HIGH':
                    await emergency_de_risk(severity="HIGH")
                    
                last_phase7_check = current_time

            # Periodic Reporting & Maintenance
            if cycle_start - last_status_report >= 21600: # 6h
                daily_summary = generate_daily_summary(DAILY_SIGNAL_COUNTER['count'], CIRCUIT_BREAKER, AUTO_BLACKLIST, MACRO_RISK_ENGINE)
                await send_telegram_message(daily_summary)
                last_status_report = cycle_start
            
            # 1. Market Scanning (Non-blocking Parallelism)
            pairs = await asyncio.to_thread(fetch_trading_pairs)
            log_message(f"📡 Found {len(pairs)} trading pairs. Scanning in parallel (Semaphore=5)...")
            
            tasks = [semaphore_process(p) for p in pairs]
            await asyncio.gather(*tasks)
                
            # Cycle Synchronization
            elapsed = time.time() - cycle_start
            await asyncio.sleep(max(0, 600 - elapsed))
            
        except Exception as e:
            log_message(f"Critical error in main loop: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log_message("System terminated by operator.")
    except Exception as e:
        log_message(f"FATAL SYSTEM ERROR: {e}")
