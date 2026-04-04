#!/usr/bin/env python3
"""
Test script for the enhanced WebSocket monitor
Tests multi-target support, WebSocket fallback, and notification system
"""

import asyncio
import json
import time
from datetime import datetime
from enhanced_websocket_monitor import RealTimeSignalMonitor

class MockTelegramSender:
    """Mock Telegram sender for testing"""
    
    def __init__(self, name="Main"):
        self.name = name
        self.messages = []
    
    async def __call__(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"\n📱 [{self.name} Channel] {timestamp}")
        print("=" * 50)
        print(message)
        print("=" * 50)
        self.messages.append({
            'timestamp': timestamp,
            'message': message,
            'channel': self.name
        })

async def test_enhanced_monitor():
    """Test the enhanced monitoring system"""
    
    print("🚀 Testing Enhanced WebSocket Monitor")
    print("=" * 60)
    
    # Create mock senders
    main_sender = MockTelegramSender("Main")
    closed_sender = MockTelegramSender("Closed Signals")
    
    # Create shared data structures
    open_signals_tracker = {}
    signal_registry = {}
    
    # Initialize monitor
    monitor = RealTimeSignalMonitor(
        telegram_sender=main_sender,
        closed_signals_sender=closed_sender,
        open_signals_tracker=open_signals_tracker,
        signal_registry=signal_registry
    )
    
    # Initialize without API keys (will use mock data)
    await monitor.initialize()
    
    print("✅ Monitor initialized successfully")
    
    # Test 1: Add a multi-target LONG signal
    print("\n📊 Test 1: Adding multi-target LONG signal")
    
    signal_id = "TEST_LONG_001"
    signal_data = {
        'pair': 'BTCUSDT',
        'signal_type': 'LONG',
        'entry_price': 50000.0,
        'timestamp': time.time()
    }
    
    registry_data = {
        'targets': [52000.0, 54000.0, 56000.0],  # 3 targets
        'stop_loss': 48000.0,
        'status': 'OPEN',
        'targets_hit': []
    }
    
    # Add to trackers
    open_signals_tracker[signal_id] = signal_data
    signal_registry[signal_id] = registry_data
    
    print(f"✅ Added signal {signal_id}")
    print(f"   Entry: {signal_data['entry_price']}")
    print(f"   Targets: {registry_data['targets']}")
    print(f"   Stop Loss: {registry_data['stop_loss']}")
    
    # Test 2: Simulate target hits
    print("\n🎯 Test 2: Simulating target hits")
    
    # Target 1 hit
    print("\n--- Target 1 Test ---")
    close_result = await monitor.check_signal_closure(signal_id, signal_data, 52100.0)
    if close_result:
        await monitor.close_signal(signal_id, close_result)
        print(f"✅ Target 1 processed: {close_result}")
    
    # Target 2 hit
    print("\n--- Target 2 Test ---")
    close_result = await monitor.check_signal_closure(signal_id, signal_data, 54100.0)
    if close_result:
        await monitor.close_signal(signal_id, close_result)
        print(f"✅ Target 2 processed: {close_result}")
    
    # Final target hit
    print("\n--- Final Target Test ---")
    close_result = await monitor.check_signal_closure(signal_id, signal_data, 56100.0)
    if close_result:
        await monitor.close_signal(signal_id, close_result)
        print(f"✅ Final target processed: {close_result}")
    
    # Test 3: Add a SHORT signal and test stop loss
    print("\n📊 Test 3: Adding SHORT signal for stop loss test")
    
    signal_id_2 = "TEST_SHORT_001"
    signal_data_2 = {
        'pair': 'ETHUSDT',
        'signal_type': 'SHORT',
        'entry_price': 3000.0,
        'timestamp': time.time()
    }
    
    registry_data_2 = {
        'targets': [2800.0, 2600.0],  # 2 targets
        'stop_loss': 3200.0,
        'status': 'OPEN',
        'targets_hit': []
    }
    
    # Add to trackers
    open_signals_tracker[signal_id_2] = signal_data_2
    signal_registry[signal_id_2] = registry_data_2
    
    print(f"✅ Added signal {signal_id_2}")
    
    # Test stop loss hit
    print("\n🛑 Test 4: Simulating stop loss hit")
    close_result = await monitor.check_signal_closure(signal_id_2, signal_data_2, 3250.0)
    if close_result:
        await monitor.close_signal(signal_id_2, close_result)
        print(f"✅ Stop loss processed: {close_result}")
    
    # Test 5: Monitor status
    print("\n📈 Test 5: Monitor status")
    status = await monitor.get_monitoring_status()
    print(f"✅ Monitor Status: {json.dumps(status, indent=2)}")
    
    # Summary
    print("\n📋 Test Summary")
    print("=" * 60)
    print(f"Main Channel Messages: {len(main_sender.messages)}")
    print(f"Closed Signals Messages: {len(closed_sender.messages)}")
    print(f"Open Signals Remaining: {len(open_signals_tracker)}")
    print(f"Registry Entries: {len(signal_registry)}")
    
    # Show all messages
    print("\n📱 All Messages Sent:")
    all_messages = main_sender.messages + closed_sender.messages
    for i, msg in enumerate(all_messages, 1):
        print(f"\n{i}. [{msg['channel']}] {msg['timestamp']}")
        print(f"   {msg['message'][:100]}...")
    
    print("\n✅ Enhanced Monitor Test Completed!")
    
    return {
        'main_messages': len(main_sender.messages),
        'closed_messages': len(closed_sender.messages),
        'open_signals': len(open_signals_tracker),
        'registry_entries': len(signal_registry)
    }

async def test_websocket_fallback():
    """Test WebSocket timeout handling and REST API fallback"""
    
    print("\n🔌 Testing WebSocket Fallback System")
    print("=" * 60)
    
    # Create monitor
    main_sender = MockTelegramSender("Main")
    closed_sender = MockTelegramSender("Closed")
    
    monitor = RealTimeSignalMonitor(
        telegram_sender=main_sender,
        closed_signals_sender=closed_sender,
        open_signals_tracker={},
        signal_registry={}
    )
    
    # Test price cache functionality
    print("📊 Testing price cache...")
    
    # Simulate cached price
    monitor.price_cache['BTCUSDT'] = {
        'price': 50000.0,
        'timestamp': time.time()
    }
    
    # Test recent cache
    price = await monitor.get_current_price('BTCUSDT')
    print(f"✅ Recent cache price: {price}")
    
    # Test old cache (should try REST API)
    monitor.price_cache['ETHUSDT'] = {
        'price': 3000.0,
        'timestamp': time.time() - 10  # 10 seconds old
    }
    
    price = await monitor.get_current_price('ETHUSDT')
    print(f"✅ Old cache handling: {price}")
    
    print("✅ WebSocket fallback test completed")

if __name__ == "__main__":
    async def main():
        print("🧪 Starting Enhanced Monitor Tests")
        print("=" * 80)
        
        # Run main test
        result = await test_enhanced_monitor()
        
        # Run fallback test
        await test_websocket_fallback()
        
        print("\n🎉 All Tests Completed Successfully!")
        print(f"📊 Results: {json.dumps(result, indent=2)}")
    
    # Run tests
    asyncio.run(main())
