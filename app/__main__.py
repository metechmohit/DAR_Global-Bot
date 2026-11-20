import argparse
import json
import logging
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="DarGlobal & Wasalt Property Atlas")
    subs = parser.add_subparsers(dest="command", required=True)
    server = subs.add_parser("serve", help="Run the local chatbot")
    server.add_argument("--host")
    server.add_argument("--port", type=int)
    server.add_argument("--production", action="store_true", help="Serve through Waitress (required in Docker)")
    subs.add_parser("ingest", help="Build normalized CSV exports and the SQLite search index")
    crawl = subs.add_parser("crawl", help="Collect publicly accessible pages into raw CSV")
    crawl.add_argument("--source", choices=["all", "darglobal", "wasalt"], default="all")
    crawl.add_argument("--max-pages", type=int, default=250, help="0 means no page-count cap")
    crawl.add_argument("--delay", type=float, default=2)
    crawl.add_argument("--browser", action="store_true")
    crawl.add_argument("--include-arabic", action="store_true")
    crawl.add_argument("--refresh", action="store_true", help="Start a fresh queue rather than resuming")
    crawl.add_argument("--urls-file", type=Path, help="Additional public URLs, one per line")
    semantic = subs.add_parser("embed", help="Build optional local multilingual embeddings")
    semantic.add_argument("--model")
    subs.add_parser("doctor", help="Check runtime, index, key presence and network access")
    subs.add_parser("check-model", help="Make one small OpenRouter request using the configured key")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "serve":
        from .server import serve
        serve(args.host, args.port, args.production)
    elif args.command == "ingest":
        from .ingest import build
        print(json.dumps(build(), indent=2))
    elif args.command == "crawl":
        from .crawl import Collector
        from .ingest import build
        urls = [line.strip() for line in args.urls_file.read_text().splitlines() if line.strip() and not line.startswith("#")] if args.urls_file else []
        worker = Collector(args.source, args.max_pages, args.delay, args.browser, args.include_arabic, args.refresh)
        print(json.dumps(worker.run(urls), indent=2))
        print(json.dumps(build(), indent=2))
    elif args.command == "embed":
        from .semantic import build_semantic
        try:
            print(json.dumps(build_semantic(args.model), indent=2))
        except ImportError:
            raise SystemExit("Install optional packages: python3 -m pip install -r requirements-semantic.txt")
    elif args.command == "check-model":
        from .openrouter import completion, ModelError
        try:
            text, model = completion([{"role": "user", "content": "Reply with just OK."}], max_tokens=30)
            print(json.dumps({"model": model, "response": text}))
        except ModelError as exc:
            raise SystemExit(str(exc))
    elif args.command == "doctor":
        import socket
        import sqlite3
        import sys
        from .config import DB, RAW
        from .openrouter import configured
        print("Python:", sys.version.split()[0])
        print("OpenRouter key present:", configured())
        print("Raw CSV files:", len(list(RAW.glob("*.csv"))))
        print("Search index:", DB.exists())
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE test USING fts5(text)")
        print("SQLite FTS5: available")
        import importlib.util
        from .config import LOCAL_CACHE, MODEL_CACHE
        print("Virtual environment:", sys.prefix != sys.base_prefix)
        print("Local cache:", LOCAL_CACHE)
        print("Embedding dependency installed:", bool(importlib.util.find_spec("sentence_transformers")))
        print("Embedding weights cache exists:", MODEL_CACHE.exists())
        from .config import DATA
        print("Semantic index exists:", (DATA / "semantic/chunks.json").exists())
        for host in ("darglobal.co.uk", "wasalt.sa", "openrouter.ai"):
            try:
                socket.getaddrinfo(host, 443)
                print(host + ": DNS OK")
            except OSError:
                print(host + ": DNS/network unavailable in this process")


if __name__ == "__main__":
    main()
