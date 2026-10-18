"""API FastAPI privada: sem logs de acesso/IP, sem cookies, sem histórico de buscas."""
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

from indexer import InvertedIndex
from ranker import search

DB = os.environ.get("INDEX_DB", "index.db")
STATIC = Path(__file__).parent / "static"
logging.getLogger("uvicorn.access").disabled = True
InvertedIndex(DB).close()  # garante que o schema exista

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def privacy_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'")
    return resp  # nenhum Set-Cookie é emitido em lugar algum


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, max_length=200), page: int = Query(1, ge=1, le=50)):
    idx = InvertedIndex(DB, readonly=True)  # consulta só em banco local, nada é gravado
    try:
        return search(idx, q, 10, (page - 1) * 10)
    finally:
        idx.close()


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8000)),
                access_log=False, log_level="warning")
