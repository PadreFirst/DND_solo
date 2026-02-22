import os

skip = ('Boss', 'dnd web vers old', '__pycache__', '.git', 'node_modules', 'tests')
counts = {}
for r, ds, fs in os.walk('.'):
    if any(s in r for s in skip):
        continue
    for f in fs:
        ext = os.path.splitext(f)[1]
        if ext in ('.py', '.txt', '.html', '.sh', '.toml', '.cfg'):
            n = sum(1 for _ in open(os.path.join(r, f), encoding='utf-8', errors='ignore'))
            counts[ext] = counts.get(ext, 0) + n

for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'{k:8s} {v:>6d}')
print(f'{"TOTAL":8s} {sum(counts.values()):>6d}')
