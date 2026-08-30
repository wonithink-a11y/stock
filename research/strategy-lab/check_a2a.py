import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'research', 'strategy-lab'))
from engine.data.a2aProvider import A2aProvider
p = A2aProvider(repo_root='.')
bars = p.load(['000020'], '2026-01-01', '2026-01-31')
if bars and '000020' in bars:
    print('Columns:', list(bars['000020'].columns))
    print('Shape:', bars['000020'].shape)
else:
    print('No bars for 000020')
    print('Available tickers count:', len(p.tickers) if hasattr(p, 'tickers') else 'N/A')