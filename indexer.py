"""Índice invertido sobre SQLite: tokenização + armazenamento de postings."""
import re
import sqlite3
import time
import unicodedata
from collections import Counter

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por para com sem e ou que se ao aos
the an of to in on at by for with and or is are was be it this that as from
""".split())
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE NOT NULL,
  title TEXT, description TEXT, headings TEXT, body TEXT,
  length INTEGER NOT NULL, crawled_at REAL
);
CREATE TABLE IF NOT EXISTS postings(
  term TEXT NOT NULL, doc_id INTEGER NOT NULL, tf INTEGER NOT NULL,
  PRIMARY KEY(term, doc_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_postings_doc ON postings(doc_id);
"""


def tokenize(text: str) -> list[str]:
    """Minúsculas, remove acentos e pontuação, descarta stopwords."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in TOKEN_RE.findall(text) if 1 < len(t) <= 40 and t not in STOPWORDS]


class InvertedIndex:
    def __init__(self, path: str = "index.db", readonly: bool = False):
        if readonly:
            self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        else:
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)

    def add_document(self, url, title, description, headings, body) -> bool:
        # Pesos: título x3, descrição x2, cabeçalhos x2, corpo x1
        weighted = Counter()
        for text, w in ((title, 3), (description, 2), (" ".join(headings), 2), (body, 1)):
            for tok in tokenize(text):
                weighted[tok] += w
        if not weighted:
            return False
        length = sum(weighted.values())
        fields = (title, description, " | ".join(headings), body[:20000], length, time.time())
        cur = self.db.cursor()
        row = cur.execute("SELECT id FROM docs WHERE url=?", (url,)).fetchone()
        if row:
            doc_id = row[0]
            cur.execute("DELETE FROM postings WHERE doc_id=?", (doc_id,))
            cur.execute("UPDATE docs SET title=?,description=?,headings=?,body=?,length=?,crawled_at=? WHERE id=?",
                        fields + (doc_id,))
        else:
            cur.execute("INSERT INTO docs(title,description,headings,body,length,crawled_at,url) "
                        "VALUES(?,?,?,?,?,?,?)", fields + (url,))
            doc_id = cur.lastrowid
        cur.executemany("INSERT INTO postings(term,doc_id,tf) VALUES(?,?,?)",
                        [(t, doc_id, c) for t, c in weighted.items()])
        self.db.commit()
        return True

    def doc_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

    def postings(self, term: str):
        return self.db.execute(
            "SELECT p.doc_id, p.tf, d.length FROM postings p JOIN docs d ON d.id=p.doc_id WHERE p.term=?",
            (term,)).fetchall()

    def get_docs(self, ids):
        q = ",".join("?" * len(ids))
        rows = self.db.execute(
            f"SELECT id,url,title,description,body FROM docs WHERE id IN ({q})", list(ids)).fetchall()
        return {r[0]: r[1:] for r in rows}

    def close(self):
        self.db.close()
