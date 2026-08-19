"""
Đo thời gian + RAM cho pipeline (analyze 10 job / crawl+analyze).

Chạy từ root project (đã activate .venv, Postgres + Ollama sẵn sàng):

  python scripts/benchmark.py
  python scripts/benchmark.py --limit 10
  python scripts/benchmark.py --crawl --limit 10 -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1
  python scripts/benchmark.py --analyze-only --limit 10

Output mẫu:
  phase          seconds   peak_rss_mb   delta_rss_mb
  analyze           85.2        2140.5         420.1
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

# --- path project ---
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("benchmark")

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore
    logger.warning("Chưa có psutil — chỉ đo thời gian. Cài: pip install psutil")


@dataclass
class PhaseResult:
    name: str
    seconds: float = 0.0
    peak_rss_mb: float = 0.0
    start_rss_mb: float = 0.0
    delta_rss_mb: float = 0.0
    extra: dict = field(default_factory=dict)


def _rss_mb() -> float:
    if psutil is None:
        return 0.0
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _system_ram() -> tuple[float, float]:
    """(available_mb, total_mb)"""
    if psutil is None:
        return 0.0, 0.0
    v = psutil.virtual_memory()
    return v.available / (1024 * 1024), v.total / (1024 * 1024)


class MemProbe:
    """Sample RSS định kỳ trong lúc chạy phase (thread chính + child không đo riêng)."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak = _rss_mb()
        self._stop = False
        self._thread = None

    def start(self):
        if psutil is None:
            return
        import threading

        self.peak = _rss_mb()

        def _loop():
            while not self._stop:
                self.peak = max(self.peak, _rss_mb())
                time.sleep(self.interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop = True
        if self._thread:
            self._thread.join(timeout=2)
        self.peak = max(self.peak, _rss_mb())
        return self.peak


def run_crawl(scrapy_a: list[str], max_pages: int | None, max_jobs: int | None = None) -> PhaseResult:
    """Crawl qua subprocess — đo wall time; RSS của process con không gộp vào peak app."""
    crawler_dir = ROOT / "src" / "job_crawler"
    if not (crawler_dir / "scrapy.cfg").exists():
        crawler_dir = ROOT / "job_crawler"

    cmd = ["scrapy", "crawl", "generic_job_spider"]
    for item in scrapy_a:
        cmd.extend(["-a", item])
    if max_pages is not None:
        cmd.extend(["-a", f"max_pages={max_pages}"])
    if max_jobs is not None:
        cmd.extend(["-a", f"max_jobs={max_jobs}"])

    env = os.environ.copy()
    # Giới hạn nhẹ nếu user muốn crawl nhanh cho benchmark
    env.setdefault("MAX_PAGES", str(max_pages or 1))

    logger.info("CRAWL: %s", " ".join(cmd))
    start_rss = _rss_mb()
    probe = MemProbe()
    probe.start()
    t0 = time.perf_counter()
    try:
        # Không capture output để thấy log scrapy
        proc = subprocess.run(cmd, cwd=str(crawler_dir), env=env)
        rc = proc.returncode
    except FileNotFoundError:
        logger.error("Không tìm thấy scrapy trong PATH/.venv")
        rc = 1
    elapsed = time.perf_counter() - t0
    peak = probe.stop()
    return PhaseResult(
        name="crawl",
        seconds=elapsed,
        peak_rss_mb=peak,
        start_rss_mb=start_rss,
        delta_rss_mb=max(0.0, peak - start_rss),
        extra={"returncode": rc},
    )


async def _run_analyze_async(limit: int, force_reindex: bool) -> dict:
    from src.analysis.run_analysis import run_analysis

    return await run_analysis(limit=limit, force_reindex=force_reindex)


def run_warmup(force_reindex: bool = False) -> PhaseResult:
    """
    Load embedding HF + CV index + LLM wrapper TRƯỚC khi đo analyze.
    Thời gian này tách riêng — không tính vào sec/job.
    """
    logger.info("WARMUP: load embedding + CV index + Ollama client...")
    start_rss = _rss_mb()
    probe = MemProbe()
    probe.start()
    t0 = time.perf_counter()

    from src.analysis.cv_indexer import get_cv_index
    from src.analysis.analyzer import setup_llm_and_query_engine

    cv_index = get_cv_index(force_reindex=force_reindex)
    engine = setup_llm_and_query_engine(cv_index)
    # Ép embedding chạy 1 lần (tránh lazy-load lần đầu trong analyze)
    try:
        _ = engine["retriever"].retrieve("python developer machine learning")
    except Exception as e:
        logger.warning("Warmup retrieve thử: %s", e)
    # Ping Ollama 1 lần (load weights vào RAM nếu chưa)
    try:
        _ = engine["llm"].complete('{"ping": true}')
    except Exception as e:
        logger.warning("Warmup LLM ping: %s (Ollama có thể load model ở request analyze đầu)", e)

    elapsed = time.perf_counter() - t0
    peak = probe.stop()
    return PhaseResult(
        name="warmup",
        seconds=elapsed,
        peak_rss_mb=peak,
        start_rss_mb=start_rss,
        delta_rss_mb=max(0.0, peak - start_rss),
        extra={"engine_ready": True},
    ), engine


def run_analyze(
    limit: int,
    force_reindex: bool,
    engine=None,
    skip_warmup: bool = False,
) -> list[PhaseResult]:
    """
    Trả về list PhaseResult:
      - nếu chưa có engine: [warmup, analyze]
      - nếu đã warmup / skip: [analyze]
    """
    results: list[PhaseResult] = []
    if engine is None and not skip_warmup:
        warm_res, engine = run_warmup(force_reindex=force_reindex)
        results.append(warm_res)
        force_reindex = False  # đã index trong warmup

    logger.info("ANALYZE (models already loaded): limit=%s", limit)
    start_rss = _rss_mb()
    probe = MemProbe()
    probe.start()
    tracemalloc.start()
    t0 = time.perf_counter()

    # Gọi pipeline nhưng tái sử dụng engine đã warm (tránh load lại)
    stats = asyncio.run(_run_analyze_with_engine(limit=limit, engine=engine, force_reindex=force_reindex))

    elapsed = time.perf_counter() - t0
    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak = probe.stop()
    results.append(
        PhaseResult(
            name="analyze",
            seconds=elapsed,
            peak_rss_mb=peak,
            start_rss_mb=start_rss,
            delta_rss_mb=max(0.0, peak - start_rss),
            extra={
                "jobs_ok": stats.get("ok", 0),
                "jobs_fail": stats.get("fail", 0),
                "jobs_skip": stats.get("skip", 0),
                "jobs_total": stats.get("total", 0),
                "traced_peak_mb": peak_traced / (1024 * 1024),
                "sec_per_job": (elapsed / stats["ok"] if stats.get("ok") else None),
                "includes_model_load": False,
            },
        )
    )
    return results


async def _run_analyze_with_engine(limit: int, engine, force_reindex: bool) -> dict:
    """
    Analyze dùng engine đã warmup. Nếu engine is None → fallback run_analysis đầy đủ
    (có load model — chỉ khi --no-warmup).
    """
    if engine is None:
        from src.analysis.run_analysis import run_analysis
        return await run_analysis(limit=limit, force_reindex=force_reindex)

    from src.analysis.analyzer import analyze_job_description, compose_job_text
    from src.database.connection import close_pool
    from src.database.queries import get_unanalyzed_jobs, update_job_with_analysis

    jobs = await get_unanalyzed_jobs(limit=limit)
    stats = {"total": len(jobs), "ok": 0, "fail": 0, "skip": 0}
    for i, row in enumerate(jobs, 1):
        job = dict(row)
        job_id = job["id"]
        title = job.get("job_title") or f"id={job_id}"
        logger.info("[%s/%s] %s", i, stats["total"], title)
        jd = compose_job_text(job)
        if len(jd) < 40:
            stats["skip"] += 1
            continue
        result = analyze_job_description(engine, jd)
        if not result:
            stats["fail"] += 1
            continue
        await update_job_with_analysis(job_id, result["match_score"], result["ai_analysis"])
        stats["ok"] += 1
    await close_pool()
    return stats


def print_report(results: list[PhaseResult], limit: int) -> None:
    avail, total = _system_ram()
    print()
    print("=" * 64)
    print("BENCHMARK REPORT — AI Job Search Pipeline")
    print("=" * 64)
    print(f"limit_jobs     : {limit}")
    if psutil:
        print(f"system_RAM     : {total:.0f} MB total, {avail:.0f} MB available (lúc bắt đầu phase cuối)")
        print(f"python_pid_RSS : đo process Python hiện tại (analyze); crawl = subprocess riêng")
    else:
        print("system_RAM     : (cài psutil để xem RSS)")
    print("-" * 64)
    hdr = f"{'phase':<12} {'seconds':>10} {'peak_rss_MB':>12} {'delta_rss_MB':>12}"
    print(hdr)
    print("-" * 64)
    for r in results:
        print(
            f"{r.name:<12} {r.seconds:>10.1f} {r.peak_rss_mb:>12.1f} {r.delta_rss_mb:>12.1f}"
        )
    print("-" * 64)
    for r in results:
        if r.name == "analyze" and r.extra:
            ok = r.extra.get("jobs_ok") or 0
            total_j = r.extra.get("jobs_total") or 0
            spj = r.extra.get("sec_per_job")
            print(f"analyze jobs  : total={total_j} ok={ok} fail={r.extra.get('jobs_fail')} skip={r.extra.get('jobs_skip')}")
            if spj:
                print(f"sec / job OK  : {spj:.1f}s")
            if r.extra.get("traced_peak_mb"):
                print(f"tracemalloc   : peak {r.extra['traced_peak_mb']:.1f} MB (Python alloc, không gồm native/HF/Ollama)")
    print()
    print("Ghi chú:")
    print("  - warmup     : load embedding HF + CV index + ping Ollama (KHÔNG tính vào sec/job).")
    print("  - analyze    : chỉ inference từng job (models đã vào RAM).")
    print("  - --no-warmup: gộp load model vào analyze (cold start, số liệu cao hơn thực tế steady-state).")
    print("  - peak_rss_MB: RSS process Python (gồm HF embed). Ollama là process riêng:")
    print("                 docker stats  |  ollama ps")
    print("=" * 64)


def main():
    parser = argparse.ArgumentParser(description="Benchmark thời gian + RAM pipeline")
    parser.add_argument("--limit", type=int, default=10, help="Số job analyze (mặc định 10)")
    parser.add_argument("--crawl", action="store_true", help="Chạy crawl trước analyze")
    parser.add_argument("--analyze-only", action="store_true", help="Chỉ analyze (mặc định nếu không --crawl)")
    parser.add_argument("--force-reindex", action="store_true", help="Tạo lại CV index")
    parser.add_argument("--max-pages", type=int, default=1, help="max_pages khi crawl (benchmark)")
    parser.add_argument("--max-jobs", type=int, default=None, help="Giới hạn số job detail khi crawl")
    parser.add_argument("-a", action="append", dest="scrapy_a", default=[], help="Scrapy -a key=value")
    args = parser.parse_args()

    do_crawl = args.crawl
    do_analyze = True  # luôn đo analyze trừ khi chỉ muốn crawl? user hỏi 10 job + analyze
    if args.analyze_only:
        do_crawl = False

    results: list[PhaseResult] = []

    if do_crawl:
        if not args.scrapy_a:
            args.scrapy_a = [
                "site_name=topcv",
                "keyword=ai-engineer",
                "location=ha-noi",
                "exp=1",
            ]
            logger.info("Dùng scrapy args mặc định: %s", args.scrapy_a)
        results.append(run_crawl(args.scrapy_a, args.max_pages, getattr(args, 'max_jobs', None)))

    if do_analyze:
        no_warmup = getattr(args, "no_warmup", False)
        if no_warmup:
            # Đo cả load model (cold start) — 1 phase analyze
            results.extend(
                run_analyze(
                    limit=args.limit,
                    force_reindex=args.force_reindex,
                    engine=None,
                    skip_warmup=True,
                )
            )
        else:
            # Mặc định: warmup riêng + analyze chỉ inference
            results.extend(
                run_analyze(
                    limit=args.limit,
                    force_reindex=args.force_reindex,
                    engine=None,
                    skip_warmup=False,
                )
            )

    print_report(results, limit=args.limit)


if __name__ == "__main__":
    main()