"""Crawler assíncrono BFS com robots.txt, extração de metadados e indexação."""
import asyncio
import re
import time
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import aiohttp

from indexer import InvertedIndex

UA = "MotorBuscaBot/1.0 (+self-hosted; respeita robots.txt)"
MAX_BYTES = 1_500_000
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|pdf|zip|gz|rar|mp[34]|avi|mov|css|js|exe|dmg|apk)$", re.I)


def normalize(url: str):
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or SKIP_EXT.search(p.path):
        return None
    return urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))


class PageParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.description, self.noindex = "", "", False
        self.headings, self.links, self.text = [], [], []
        self._skip, self._in_title, self._head, self._buf = 0, False, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name, content = (a.get("name") or "").lower(), a.get("content") or ""
            if name == "description":
                self.description = content.strip()
            elif name == "robots" and "noindex" in content.lower():
                self.noindex = True
        elif tag == "a" and a.get("href") and "nofollow" not in (a.get("rel") or "").lower():
            self.links.append(a["href"])
        elif tag in ("h1", "h2"):
            self._head, self._buf = tag, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == self._head:
            h = " ".join("".join(self._buf).split())
            if h:
                self.headings.append(h)
            self._head = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            if self._head:
                self._buf.append(data)
            self.text.append(data)


class Robots:
    def __init__(self, session):
        self.session, self.cache = session, {}

    async def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = RobotFileParser()
            try:
                async with self.session.get(base + "/robots.txt", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        rp.parse((await r.text(errors="replace")).splitlines())
                    else:
                        rp.parse([])  # sem robots.txt: tudo permitido
            except Exception:
                rp.parse([])
            self.cache[base] = rp
        return self.cache[base].can_fetch(UA, url)


class Crawler:
    def __init__(self, index: InvertedIndex, seeds, max_pages=100, max_depth=2,
                 concurrency=5, same_domain=False, delay=1.0):
        self.index, self.max_pages, self.max_depth = index, max_pages, max_depth
        self.concurrency, self.same_domain, self.delay = concurrency, same_domain, delay
        self.seeds = [u for u in (normalize(s) for s in seeds) if u]
        self.allowed_hosts = {urlparse(u).netloc for u in self.seeds}
        self.seen, self.pages = set(), 0
        self.locks, self.last = {}, {}

    async def run(self) -> int:
        self.queue = asyncio.Queue()
        for u in self.seeds:
            if u not in self.seen:
                self.seen.add(u)
                self.queue.put_nowait((u, 0))
        async with aiohttp.ClientSession(headers={"User-Agent": UA},
                                         timeout=aiohttp.ClientTimeout(total=15)) as session:
            self.robots = Robots(session)
            workers = [asyncio.create_task(self._worker(session)) for _ in range(self.concurrency)]
            await self.queue.join()
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        return self.pages

    async def _worker(self, session):
        while True:
            url, depth = await self.queue.get()
            try:
                if self.pages < self.max_pages:
                    await self._process(session, url, depth)
            except Exception as e:
                print(f"[erro] {url}: {type(e).__name__}")
            finally:
                self.queue.task_done()

    async def _polite(self, host):
        lock = self.locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.last.get(host, 0) + self.delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.last[host] = time.monotonic()

    async def _process(self, session, url, depth):
        if not await self.robots.allowed(url):
            print(f"[robots] bloqueado: {url}")
            return
        await self._polite(urlparse(url).netloc)
        async with session.get(url) as resp:
            if resp.status != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                return
            raw = await resp.content.read(MAX_BYTES)
            final_url = str(resp.url)
            try:
                html = raw.decode(resp.charset or "utf-8", errors="replace")
            except LookupError:
                html = raw.decode("utf-8", errors="replace")
        parser = PageParser()
        parser.feed(html)
        if not parser.noindex:
            body = " ".join(" ".join(parser.text).split())
            if self.index.add_document(url, " ".join(parser.title.split()), parser.description,
                                       parser.headings, body):
                self.pages += 1
                print(f"[{self.pages}/{self.max_pages}] d={depth} {url}")
        if depth >= self.max_depth or len(self.seen) >= self.max_pages * 20:
            return
        for href in parser.links:
            link = normalize(urljoin(final_url, href))
            if not link or link in self.seen:
                continue
            if self.same_domain and urlparse(link).netloc not in self.allowed_hosts:
                continue
            self.seen.add(link)
            self.queue.put_nowait((link, depth + 1))
