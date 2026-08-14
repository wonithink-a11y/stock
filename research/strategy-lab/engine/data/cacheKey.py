"""Single implementation of the CACHE CONTRACT's key. Shared by every concrete
PriceProvider (A2a today, A2b later) so the invalidation rule cannot drift between
implementations.

If any of the five inputs changes, the digest changes, and a changed digest means
the cache file simply does not exist under that name - "invalidation" does not need
a separate comparison step for the common case. The .meta.json sidecar written
alongside the cache (see a2aProvider.py) is a second, explicit check for the
uncommon case (e.g. a stale file left over from a bug) - belt and suspenders,
matching the contract's "존재하더라도 불일치하면 자동 무효화" wording literally.
"""
import hashlib
import json

CACHE_SCHEMA_VERSION = "1"


def build_cache_key(manifest_hash, universe_hash, ticker_set, start, end):
    payload = {
        "manifestHash": manifest_hash,
        "universeHash": universe_hash,
        "tickerSetHash": hashlib.sha256(",".join(sorted(ticker_set)).encode()).hexdigest(),
        "start": start,
        "end": end,
        "schemaVersion": CACHE_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    return digest, payload
