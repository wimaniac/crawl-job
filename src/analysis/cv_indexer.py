"""Index CV PDF bằng LlamaIndex + embedding HuggingFace (local, không cần OpenAI)."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CV_DIR = PROJECT_ROOT / "cv_data"
PERSIST_DIR = PROJECT_ROOT / "storage" / "cv_index"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "phi3:mini")

# Model đa ngữ — phù hợp CV/JD tiếng Việt + tiếng Anh
# Lần đầu sẽ tải về (~100–500MB) vào cache HuggingFace
HF_EMBED_MODEL = os.getenv(
    "HF_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def _configure_settings() -> None:
    """LLM = Ollama local; embedding = HuggingFace local — không dùng OpenAI.

    Set context_window/num_ctx tương tự analyzer.py — Settings.llm là LLM
    mặc định toàn cục của LlamaIndex, có thể được dùng ngầm ở một số bước
    (vd query transform) ngay cả khi query engine chính dùng llm riêng.
    Không giới hạn ở đây dễ dính lại đúng lỗi Ollama cấp phát KV-cache
    khổng lồ (xem ghi chú chi tiết trong analyzer.py).
    """
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    Settings.llm = Ollama(
        model=LLM_MODEL,
        base_url=OLLAMA_HOST,
        request_timeout=180.0,
        context_window=num_ctx,
        additional_kwargs={"num_ctx": num_ctx},
    )
    Settings.embed_model = HuggingFaceEmbedding(
        model_name=HF_EMBED_MODEL,
        # device="cuda" nếu có GPU; mặc định CPU
        trust_remote_code=False,
    )
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 50


def get_cv_index(force_reindex: bool = False) -> VectorStoreIndex:
    """
    Tạo hoặc tải VectorStoreIndex từ PDF trong cv_data/.
    Đổi embedding model → nên --force-reindex một lần.
    """
    _configure_settings()

    try:
        cv_file = next(CV_DIR.glob("*.pdf"))
    except StopIteration:
        raise FileNotFoundError(
            f"Không tìm thấy PDF trong {CV_DIR}. Hãy đặt file CV (.pdf) vào đó."
        )

    should_reindex = True
    if not force_reindex and PERSIST_DIR.exists():
        if PERSIST_DIR.stat().st_mtime >= cv_file.stat().st_mtime:
            logging.info(f"Tải CV index có sẵn từ {PERSIST_DIR}")
            should_reindex = False

    if should_reindex:
        logging.info(
            f"Tạo index từ '{cv_file.name}' | embed={HF_EMBED_MODEL} ..."
        )
        if PERSIST_DIR.exists():
            shutil.rmtree(PERSIST_DIR)

        reader = SimpleDirectoryReader(input_dir=str(CV_DIR), required_exts=[".pdf"])
        documents = reader.load_data()
        if not documents:
            raise RuntimeError("Không đọc được nội dung PDF.")

        splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
        index = VectorStoreIndex.from_documents(documents, transformations=[splitter])
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(persist_dir=str(PERSIST_DIR))
        logging.info(f"Đã lưu index → {PERSIST_DIR}")
    else:
        storage = StorageContext.from_defaults(persist_dir=str(PERSIST_DIR))
        index = load_index_from_storage(storage)
        logging.info("Tải index thành công.")

    return index


if __name__ == "__main__":
    print(f"CV_DIR={CV_DIR}")
    print(f"PERSIST_DIR={PERSIST_DIR}")
    print(f"HF_EMBED_MODEL={HF_EMBED_MODEL}")
    idx = get_cv_index(force_reindex=True)
    print(f"index_id={idx.index_id}")