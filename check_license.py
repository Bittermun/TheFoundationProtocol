import os
import re

missing = []
license_pattern = re.compile(r'SPDX-License-Identifier|Apache License|Apache-2\.0')

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'node_modules', '.pytest_cache']]
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    first_10 = ''.join([file.readline() for _ in range(10)])
                    if not license_pattern.search(first_10):
                        missing.append(path)
            except:
                pass

for path in missing:
    print(path)
