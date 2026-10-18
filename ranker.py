"""Processamento de consultas e ranking TF-IDF com bônus de cobertura."""
import math
import re
from collections import defaultdict

from indexer import InvertedIndex, tokenize


def make_snippet(body: str, description: str, query: str, size: int = 180) -> str:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    low = body.lower()
    pos = min((p for p in (low.find(w) for w in words) if p >= 0), default=-1)
    if pos < 0:
        return (description or body[:size]).strip()[:size]
    start = max(0, pos - size // 3)
    text = " ".join(body[start:start + size].split())
    return ("…" if start else "") + text + "…"


def search(idx: InvertedIndex, query: str, limit: int = 10, offset: int = 0) -> dict:
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms:
        return {"total": 0, "results": []}
    n_docs = idx.doc_count()
    scores, matched = defaultdict(float), defaultdict(int)
    for term in terms:
        rows = idx.postings(term)
        if not rows:
            continue
        idf = math.log(1 + n_docs / len(rows))
        for doc_id, tf, length in rows:
            scores[doc_id] += (1 + math.log(tf)) * idf / (1 + math.log(length))
            matched[doc_id] += 1
    for doc_id in scores:  # documentos com todos os termos sobem no ranking
        scores[doc_id] *= (matched[doc_id] / len(terms)) ** 2
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    page = ranked[offset:offset + limit]
    docs = idx.get_docs([d for d, _ in page]) if page else {}
    results = []
    for doc_id, score in page:
        url, title, desc, body = docs[doc_id]
        results.append({"url": url, "title": title or url, "snippet": make_snippet(body, desc, query),
                        "score": round(score, 4)})
    return {"total": len(ranked), "results": results}
