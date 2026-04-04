import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv('.env')
token = os.getenv('TELEGRAM_TOKEN', '').strip('\'\"')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip('\'\"')

signal_msg = """📉 **NEW SHORT SIGNAL**
TP1: 3.0
TP2: 1.0
"""
res1 = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat_id, 'text': signal_msg, 'parse_mode': 'html'})
data = res1.json()

if data.get('ok'):
    msg_id = data['result']['message_id']
    time.sleep(4)
    res2 = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat_id, 'text': 'Stop: 5.5', 'reply_to_message_id': msg_id})
    print("Done")
