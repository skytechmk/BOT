import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram_handler import process_cornix_response, SIGNAL_REGISTRY, register_signal

async def test_integration():
    print("🚀 Starting Cornix Integration Test...")
    
    # 1. Register a dummy signal
    signal_id = "test-signal-123"
    msg_id = 9999
    register_signal(
        signal_id=signal_id,
        pair="ONTUSDT",
        signal="SHORT",
        price=0.1256,
        confidence=0.25,
        targets=[0.11, 0.10],
        stop_loss=0.13,
        leverage=10,
        telegram_message_id=msg_id
    )
    
    print(f"✅ Registered dummy signal {signal_id} with msg_id {msg_id}")
    
    # 2. Mock a Cornix "All entries achieved" message as a reply
    mock_message = "#ONT/USDT All entries achieved\nAverage Entry Price: 0.1256 💵"
    print(f"📥 Mocking Cornix message (Reply to {msg_id}):\n{mock_message}")
    
    success = process_cornix_response(mock_message, reply_id=msg_id)
    
    if success:
        print("✅ Successfully matched and processed Cornix response via Reply ID!")
        updated_sig = SIGNAL_REGISTRY[signal_id]
        print(f"📝 Updated Status: {updated_sig['cornix_response']['status']}")
        print(f"📝 Parsed Entry: {updated_sig['cornix_response']['parsed_data'].get('entry')}")
    else:
        print("❌ Failed to process Cornix response")

    # 3. Mock a Target Achieved message (Matching by Pair)
    mock_tp_message = "#ONT/USDT Target 1 achieved 🚀"
    print(f"\n📥 Mocking Cornix TP message (No Reply ID, matching by Pair):")
    
    success_tp = process_cornix_response(mock_tp_message)
    
    if success_tp:
        print("✅ Successfully matched TP message via Pair matching!")
    else:
        print("❌ Failed to match TP message")

if __name__ == "__main__":
    asyncio.run(test_integration())
