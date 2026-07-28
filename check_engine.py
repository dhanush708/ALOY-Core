import sys
with open('c:/Users/DHANUSH ANBU/Desktop/COPY/MYAI FINAL - Copy/conversation/engine.py', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f.readlines()):
        if 'len(history)' in line:
            print(f'Line {i+1}: {line.strip()}')
