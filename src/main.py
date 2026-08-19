"""
Entry point pipeline:
  python -m src.main --crawl -a site_name=topcv -a keyword=ai-engineer
  python -m src.main --analyze --limit 10
  python -m src.main --notify --min-score 70
  python -m src.main --crawl --analyze --notify -a site_name=topcv -a keyword=python -a location=ha-noi
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_crawler(extra_args: list[str] | None = None) -> int:
    crawler_dir = PROJECT_ROOT / "src" / "job_crawler"
    if not (crawler_dir / "scrapy.cfg").exists():
        crawler_dir = PROJECT_ROOT / "job_crawler"

    cmd = ["scrapy", "crawl", "generic_job_spider"]
    if extra_args:
        cmd.extend(extra_args)

    logger.info("Chạy crawler: %s (cwd=%s)", " ".join(cmd), crawler_dir)
    try:
        subprocess.run(cmd, cwd=str(crawler_dir), check=True)
        logger.info("Crawl xong.")
        return 0
    except FileNotFoundError:
        logger.error("Không tìm thấy lệnh scrapy.")
        return 1
    except subprocess.CalledProcessError as e:
        logger.error("Scrapy lỗi, code=%s", e.returncode)
        return e.returncode


def run_analyze(limit: int | None = None, force_reindex: bool = False) -> int:
    from src.analysis.run_analysis import run_analysis

    stats = asyncio.run(run_analysis(limit=limit, force_reindex=force_reindex))
    # fail một phần vẫn coi là chạy xong pipeline (không chặn --notify)
    if stats.get("ok", 0) == 0 and stats.get("fail", 0) > 0:
        return 2
    return 0


def run_notify(min_score: int = 70, limit: int | None = None, dry_run: bool = False) -> int:
    from src.notification.run_notify import run_notify as _run_notify

    stats = asyncio.run(_run_notify(min_score=min_score, limit=limit, dry_run=dry_run))
    if dry_run:
        return 0
    return 0 if stats.get("sent") or stats.get("found", 0) == 0 else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Job Search & Analysis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python -m src.main --crawl -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1,2,3
  python -m src.main --analyze --limit 10
  python -m src.main --notify --min-score 70
  python -m src.main --crawl --analyze --notify -a site_name=topcv -a keyword=python -a location=ha-noi
  python -m src.main --notify --dry-run
        """,
    )
    parser.add_argument("--crawl", action="store_true", help="Chạy Scrapy crawl")
    parser.add_argument("--analyze", action="store_true", help="Phân tích job chưa có score")
    parser.add_argument("--notify", action="store_true", help="Gửi email job đạt ngưỡng")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số job (analyze/notify)")
    parser.add_argument("--force-reindex", action="store_true", help="Tạo lại CV index")
    parser.add_argument("--min-score", type=int, default=70, help="Ngưỡng match_score khi notify")
    parser.add_argument("--dry-run", action="store_true", help="Notify: không gửi email thật")
    parser.add_argument("--max-jobs", type=int, default=None, help="Giới hạn số job crawl (detail)")
    parser.add_argument("--max-pages", type=int, default=None, help="Giới hạn số trang list")
    parser.add_argument(
        "-a",
        action="append",
        dest="scrapy_a",
        default=[],
        help="Scrapy -a key=value (lặp được)",
    )
    args = parser.parse_args(argv)

    if not (args.crawl or args.analyze or args.notify):
        parser.print_help()
        return 0

    code = 0
    if args.crawl:
        extra: list[str] = []
        for item in args.scrapy_a:
            extra.extend(["-a", item])
        if args.max_jobs is not None:
            extra.extend(["-a", f"max_jobs={args.max_jobs}"])
        if args.max_pages is not None:
            extra.extend(["-a", f"max_pages={args.max_pages}"])
        code = run_crawler(extra) or code

    if args.analyze:
        rc = run_analyze(limit=args.limit, force_reindex=args.force_reindex)
        code = code or rc

    if args.notify:
        rc = run_notify(min_score=args.min_score, limit=args.limit, dry_run=args.dry_run)
        code = code or rc

    return code


if __name__ == "__main__":
    sys.exit(main())