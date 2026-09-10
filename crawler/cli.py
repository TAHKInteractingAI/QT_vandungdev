import argparse
from pathlib import Path

from crawler.config import (
    DEFAULT_KEYWORD,
    DEFAULT_LANG,
    DEFAULT_PROVIDER,
    DEFAULT_TIME_WINDOW,
    DEFAULT_WORKERS,
    TIMEOUT,
)
from crawler.core import crawl_google_news
from crawler.excel import export_excel_from_jsonl


def main() -> None:
    p = argparse.ArgumentParser(description="Crawl Google News MVP")
    p.add_argument("--keyword", default=DEFAULT_KEYWORD, help=f"Search keyword (default: '{DEFAULT_KEYWORD}')")
    p.add_argument("--max", type=int, default=20, dest="max_articles", help="Max articles to crawl")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of concurrent workers (default: {DEFAULT_WORKERS})")
    p.add_argument("--output", type=str, default="storage", help="Base output directory (default: 'storage')")
    p.add_argument("--lang", "--locales", "--markets", type=str, default=DEFAULT_LANG, dest="lang", help=f"Market/language code(s), e.g. 'vi', 'us', 'vi,us,jp' or preset 'top', 'global', 'asia', 'tech' (default: '{DEFAULT_LANG}')")
    p.add_argument("--time-window", "--when", type=str, default=DEFAULT_TIME_WINDOW, dest="time_window", help="News time window filter, e.g. '1d' (24h), '2d' (48h), '7d', '1h'")
    p.add_argument("--provider", type=str, default=DEFAULT_PROVIDER, help="Search engine provider: 'auto' (default), 'bing', 'google'")
    p.add_argument("--timeout", type=int, default=TIMEOUT, help=f"HTTP timeout in seconds (default: {TIMEOUT})")
    p.add_argument("--proxy", type=str, default=None, help="HTTP/HTTPS/SOCKS5 proxy URL (e.g. http://127.0.0.1:7890)")
    p.add_argument("--rotate-ua", action="store_true", help="Rotate User-Agent per request from modern browser pool")
    p.add_argument("--timezone", "--tz", type=str, default="Asia/Ho_Chi_Minh", dest="timezone", help="Timezone for naming folders and tabs (default: 'Asia/Ho_Chi_Minh')")
    p.add_argument("--no-resume", action="store_true", help="Disable checkpoint resume, start fresh")
    p.add_argument("--no-progress", action="store_true", help="Hide progress")
    p.add_argument("--export-from-jsonl", type=str, default=None, help="Re-export articles.xlsx from an existing JSONL checkpoint")
    args = p.parse_args()

    if args.export_from_jsonl:
        out_path = export_excel_from_jsonl(args.export_from_jsonl, args.output)
        print(f"[export] generated {out_path}")
        return

    try:
        result = crawl_google_news(
            args.keyword,
            args.max_articles,
            Path(args.output),
            workers=args.workers,
            proxy=args.proxy,
            rotate_ua=args.rotate_ua,
            lang=args.lang,
            time_window=args.time_window,
            timeout=args.timeout,
            resume=not args.no_resume,
            show_progress=not args.no_progress,
            timezone=args.timezone,
            provider=args.provider,
        )
        if result.get("interrupted"):
            import os
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(130)
        print(result)
    except KeyboardInterrupt:
        import os
        import sys
        print("\n[cli] Crawl process interrupted.")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(130)


if __name__ == "__main__":
    main()
