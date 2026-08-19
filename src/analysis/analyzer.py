# src/analysis/analyzer.py
"""Phân tích JD so với CV bằng LLM local (Ollama).

Không dùng query_engine text_qa (phi3 hay echo lại JD).
Luồng: retrieve chunk CV → llm.complete + format=json → parse.
"""
from __future__ import annotations

import json
import logging
import os
import re

from llama_index.core import VectorStoreIndex
from llama_index.llms.ollama import Ollama

from .cv_indexer import get_cv_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "phi3:mini")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "200"))
MAX_JD_CHARS = int(os.getenv("MAX_JD_CHARS", "2500"))
MAX_CV_CHARS = int(os.getenv("MAX_CV_CHARS", "2500"))
SIMILARITY_TOP_K = int(os.getenv("SIMILARITY_TOP_K", "3"))

SYSTEM_HINT = (
    "Bạn là hệ thống chấm điểm CV. Chỉ trả JSON. "
    "Không viết giải thích ngoài JSON."
)

PROMPT_TEMPLATE = """So sánh CV với tin tuyển dụng. Chấm điểm thực tế.

Thang điểm:
- 0-30: không liên quan / thiếu hầu hết yêu cầu
- 31-50: liên quan yếu
- 51-70: khá phù hợp, còn thiếu vài yêu cầu
- 71-85: phù hợp tốt
- 86-100: rất khớp (chỉ khi gần như đủ mọi yêu cầu chính)

Yêu cầu output (JSON thuần, không markdown):
{{"match_score": <0-100>, "ai_analysis": "<1-2 câu tiếng Việt: 1 điểm mạnh + 1 điểm thiếu>"}}

### CV
{cv_context}

### Tin tuyển dụng
{job_text}
"""


def setup_llm_and_query_engine(cv_index: VectorStoreIndex):
    """
    Trả về dict chứa llm + retriever (tương thích run_analysis cũ
    gọi setup_llm_and_query_engine rồi analyze_job_description(engine, ...)).
    """
    llm = Ollama(
        model=LLM_MODEL,
        base_url=OLLAMA_HOST,
        request_timeout=180.0,
        context_window=NUM_CTX,
        temperature=0.1,
        # Ép Ollama trả JSON hợp lệ
        additional_kwargs={
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "temperature": 0.1,
            "format": "json",
        },
    )
    retriever = cv_index.as_retriever(similarity_top_k=SIMILARITY_TOP_K)
    return {"llm": llm, "retriever": retriever, "index": cv_index}


def compose_job_text(job: dict) -> str:
    parts = []
    title = job.get("job_title") or ""
    company = job.get("company_name") or ""
    if title or company:
        parts.append(f"Vị trí: {title} | Công ty: {company}")
    if job.get("location"):
        parts.append(f"Địa điểm: {job['location']}")
    if job.get("salary_range"):
        parts.append(f"Mức lương: {job['salary_range']}")
    if job.get("experience"):
        parts.append(f"Kinh nghiệm yêu cầu: {job['experience']}")
    if job.get("job_requirements"):
        parts.append(f"Yêu cầu:\n{job['job_requirements']}")
    if job.get("job_description"):
        parts.append(f"Mô tả:\n{job['job_description']}")
    if job.get("job_benefits"):
        ben = str(job["job_benefits"])
        if len(ben) > 300:
            ben = ben[:300] + "..."
        parts.append(f"Quyền lợi:\n{ben}")
    text = "\n\n".join(parts).strip()
    if len(text) > MAX_JD_CHARS:
        text = text[:MAX_JD_CHARS] + "\n...(cắt)"
    return text


def _retrieve_cv_context(engine, job_text: str) -> str:
    retriever = engine["retriever"]
    nodes = retriever.retrieve(job_text)
    chunks = []
    for n in nodes:
        content = n.get_content() if hasattr(n, "get_content") else str(n)
        chunks.append(content.strip())
    text = "\n---\n".join(chunks)
    if len(text) > MAX_CV_CHARS:
        text = text[:MAX_CV_CHARS] + "\n...(cắt)"
    return text or "(Không lấy được đoạn CV liên quan.)"


def _clean_analysis(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"```(?:json)?|```", "", text)
    text = re.sub(
        r"(trả lời đúng|không markdown|match_score|ai_analysis\s*:)",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s{2,}", " ", text).strip(" -:\n\"'")
    if len(text) > 280:
        text = text[:277] + "..."
    return text


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    # Bỏ markdown fence nếu còn
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    score_m = re.search(r'"match_score"\s*:\s*(\d+)', text)
    if score_m:
        analysis_m = re.search(r'"ai_analysis"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        analysis = analysis_m.group(1) if analysis_m else ""
        return {"match_score": int(score_m.group(1)), "ai_analysis": analysis}
    return None


def analyze_job_description(engine, job_text: str) -> dict | None:
    """
    engine: object từ setup_llm_and_query_engine (dict llm+retriever)
            hoặc legacy query_engine (có .query) — fallback.
    """
    if not job_text or len(job_text) < 40:
        logging.warning("JD quá ngắn — bỏ qua.")
        return None

    try:
        # --- Luồng mới: retrieve + complete JSON ---
        if isinstance(engine, dict) and "llm" in engine:
            cv_context = _retrieve_cv_context(engine, job_text)
            prompt = PROMPT_TEMPLATE.format(
                cv_context=cv_context,
                job_text=job_text,
            )
            # Một số bản llama-index Ollama dùng .complete
            raw = engine["llm"].complete(prompt)
            response_text = str(raw).strip()
        else:
            # Fallback legacy query_engine
            response_text = str(engine.query(job_text)).strip()

        result = _extract_json(response_text)
        if not result:
            logging.error(f"Không parse được JSON: {response_text[:250]}")
            return None

        if "match_score" not in result:
            logging.error(f"JSON thiếu match_score: {result}")
            return None

        score = max(0, min(100, int(result["match_score"])))
        analysis = _clean_analysis(str(result.get("ai_analysis", "")))
        if not analysis:
            analysis = "Không có nhận xét chi tiết."

        logging.info(f"Phân tích OK — score={score}")
        return {"match_score": score, "ai_analysis": analysis}

    except Exception as e:
        logging.error(f"Lỗi phân tích: {e}")
        return None


if __name__ == "__main__":
    index = get_cv_index()
    engine = setup_llm_and_query_engine(index)
    sample = {
        "job_title": "Python Developer",
        "company_name": "Demo",
        "job_description": "Xây dựng API FastAPI, ETL, Scrapy, PostgreSQL.",
        "job_requirements": "3 năm Python, biết Scrapy là lợi thế.",
        "job_benefits": "Lương thỏa thuận",
    }
    print(analyze_job_description(engine, compose_job_text(sample)))