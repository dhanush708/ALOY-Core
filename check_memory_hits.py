import sys
import os
for root, _, files in os.walk('c:/Users/DHANUSH ANBU/Desktop/COPY/MYAI FINAL - Copy'):
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'Memory Hits' in content or 'memory_hits' in content.lower():
                    print(f'Found in {path}')
