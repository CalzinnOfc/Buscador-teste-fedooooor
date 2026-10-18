"""CLI do crawler. Ex.: python crawl.py --seeds seeds.txt --max-pages 200 --depth 2"""
import argparse
import asyncio

from crawler import Crawler
from indexer import InvertedIndex

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", default="seeds.txt", help="arquivo com uma URL por linha")
ap.add_argument("--db", default="index.db")
ap.add_argument("--max-pages", type=int, default=100)
ap.add_argument("--depth", type=int, default=2)
ap.add_argument("--concurrency", type=int, default=5)
ap.add_argument("--delay", type=float, default=1.0, help="segundos entre requisições ao mesmo host")
ap.add_argument("--same-domain", action="store_true", help="não sai dos domínios das sementes")
args = ap.parse_args()

with open(args.seeds, encoding="utf-8") as f:
    seeds = [l.strip() for l in f if l.strip() and not l.startswith("#")]

idx = InvertedIndex(args.db)
total = asyncio.run(Crawler(idx, seeds, args.max_pages, args.depth, args.concurrency,
                            args.same_domain, args.delay).run())
print(f"Concluído: {total} páginas indexadas. Total no índice: {idx.doc_count()}")
idx.close()
