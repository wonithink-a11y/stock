import json, gzip
with gzip.open('data/backfill/fundamentals/a3c/2025.jsonl.gz', 'rt', encoding='utf-8') as f:
    lines = [json.loads(l) for l in f.readlines()[:2]]
    for l in lines:
        keys = list(l.keys())
        print('Keys:', keys[:30])
        for k in l:
            if 'ticker' in k.lower() or 'corp' in k.lower() or 'istc' in k.lower() or 'share' in k.lower() or 'cap' in k.lower():
                print(f'  {k}: {l[k]}')