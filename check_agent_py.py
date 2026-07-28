import sys
import os
with open('c:/Users/DHANUSH ANBU/Desktop/COPY/MYAI FINAL - Copy/api/routes/agent.py', 'r', encoding='utf-8') as f:
    content = f.read()
    if 'memory' in content.lower():
        print('agent.py has memory metadata')
