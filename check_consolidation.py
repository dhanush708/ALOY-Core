import sys
with open('c:/Users/DHANUSH ANBU/Desktop/COPY/MYAI FINAL - Copy/memory/consolidation.py', 'r', encoding='utf-8') as f:
    content = f.read()
    if 'extract' in content:
        print('ConsolidationEngine has extraction logic.')
    else:
        print('ConsolidationEngine does NOT extract.')
