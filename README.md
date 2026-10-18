# Motor de Busca Privado

    pip install -r requirements.txt
    python crawl.py --seeds seeds.txt --max-pages 200 --depth 2 --same-domain
    python server.py          # http://localhost:8000

Estrutura: crawler.py (BFS + robots.txt) · indexer.py (índice invertido SQLite) ·
ranker.py (TF-IDF) · server.py (FastAPI sem logs/cookies) · static/index.html (frontend).

Variáveis: INDEX_DB, HOST, PORT. Em produção use proxy reverso (nginx/Caddy) com
access_log off e sem log de IP. Reexecute o crawl.py periodicamente para atualizar o índice.
