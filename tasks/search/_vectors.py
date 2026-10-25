"""Shared setup for the vector search templates: an index of articles with 8-dimensional
embeddings generated from a seed (no ML model needed)."""

import json
import random

DIMS = 8
CATEGORIES = ["databases", "observability", "security", "search", "cloud"]
WORDS = ["scaling", "cluster", "latency", "index", "query", "shard", "replica", "vector", "logs", "metrics",
         "alerting", "tuning", "storage", "backup", "access", "tokens", "relevance", "ranking"]


def vector(rnd):
    return [round(rnd.uniform(-1, 1), 4) for _ in range(DIMS)]


def create_articles(es, index, seed, count=300):
    rnd = random.Random(seed)
    es.put(f"/{index}", {"mappings": {"properties": {
        "title": {"type": "text"},
        "category": {"type": "keyword"},
        "embedding": {"type": "dense_vector", "dims": DIMS, "index": True, "similarity": "cosine"},
    }}})
    bulk = "".join(
        json.dumps({"index": {"_id": str(i)}}) + "\n" +
        json.dumps({"title": " ".join(rnd.sample(WORDS, 4)), "category": rnd.choice(CATEGORIES),
                    "embedding": vector(rnd)}) + "\n"
        for i in range(count))
    es.send("POST", f"/{index}/_bulk?refresh=true", bulk.encode(), "application/x-ndjson")
    # One segment per shard, so approximate kNN results don't depend on how merges happened
    es.send("POST", f"/{index}/_forcemerge?max_num_segments=1")
