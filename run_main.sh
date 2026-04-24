#!/bin/bash
cd /home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA
# Double-fork to properly detach from terminal and avoid job control issues
( exec 0<&- 1>/tmp/main_bot.log 2>&1 /root/miniconda3/bin/python3 -u main.py & )
