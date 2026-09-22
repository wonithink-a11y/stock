from pathlib import Path
_LAB = Path(__file__).resolve().parents[1]
WORK = str(_LAB / 'data' / 'crypto' / 'wonyotti-work') + '/'      # 중간 산출물(gitignore)
CRYPTO = str(_LAB / 'data' / 'crypto') + '/'
CRYPTO_WON = str(_LAB.parents[1] / 'Crypto_won') + '/'            # 원본 체결기록(gitignore)
Path(WORK).mkdir(parents=True, exist_ok=True)
