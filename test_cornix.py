import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv('.env')
token = os.getenv('TELEGRAM_TOKEN', '').strip('\'\"')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip('\'\"')

# 1. Send Fake Signal
signal_msg = """📉 **NEW SHORT SIGNAL**
3.0
1.0
"""
res1 = requests.post(
    f'https://api.telegram.org/bot{token}/sendMessage',
    json={'chat_id': chat_id, 'text': signal_msg, 'parse_mode': 'Markdown'}
)
data = res1.json()
print("Signal Response:", json.dumps(data))

if data.get('ok'):
    msg_id = data['result']['message_id']
    print(f"Got message ID: {msg_id}")
    
    # Wait for Cornix to register it
    print("Waiting 3 seconds for Cornix to process...")
    time.sleep(3)
    
    # 2. Send Trailing Reply
    stop_cmd = "Stop: 5.5"
    res2 = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={
            'chat_id': chat_id, 
            'text': stop_cmd, 
            'reply_to_message_id': msg_id,
            'parse_mode': 'Markdown'
        }
    )
    print("Reply Response:", json.dumps(res2.json()))

