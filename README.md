# AI Job Search & Analysis Pipeline

Thu thập việc làm (TopCV, …) bằng **Scrapy + Playwright**, lưu **PostgreSQL**, chấm điểm phù hợp với **CV** bằng **LLM local (Ollama)** + embedding **HuggingFace**, gửi email các job đạt ngưỡng.

## Cấu trúc

```text
src/
├── main.py                 # CLI: --crawl / --analyze / --notify
├── analysis/
│   ├── analyzer.py         # So khớp CV ↔ JD (Ollama JSON)
│   ├── cv_indexer.py       # Index CV PDF (HuggingFace embed)
│   └── run_analysis.py     # Batch analyze từ DB
├── core/
│   └── config.py           # Đọc .env
├── database/
│   ├── connection.py       # asyncpg pool
│   └── queries.py
├── notification/
│   ├── email_notifier.py
│   └── run_notify.py
└── job_crawler/
    ├── scrapy.cfg
    ├── sites_config.json
    ├── topcv_locations.json
    └── job_crawler/
        ├── spiders/generic_job_spider.py
        ├── items.py
        ├── pipelines.py
        └── settings.py
cv_data/                    # Đặt file CV .pdf tại đây
docker-compose.yml
Dockerfile
requirements.txt
.env.example
```

## Yêu cầu

- Docker + Docker Compose
- (Local không Docker) Python 3.11+, Ollama, PostgreSQL

## Chạy bằng Docker (khuyến nghị)

### 1. Chuẩn bị

```bash
cp .env.example .env
# Sửa EMAIL_* / mật khẩu DB nếu cần

mkdir -p cv_data logs
# Copy CV của bạn:
cp /path/to/your_cv.pdf cv_data/
```

### 2. Build & khởi động

```bash
docker compose up -d --build
```

Services:

| Service | Vai trò | Port |
|---------|---------|------|
| `postgres` | Database | 5432 |
| `ollama` | LLM local | 11434 |
| `ollama-init` | Pull model 1 lần rồi thoát | — |
| `app` | Code pipeline (sleep, dùng `exec`) | — |

Đợi Ollama pull xong (`phi3:mini` lần đầu có thể vài phút):

```bash
docker compose logs -f ollama-init
```

### 3. Chạy pipeline

`Dockerfile` đặt:

```dockerfile
ENTRYPOINT ["python", "-m", "src.main"]
```

→ mọi arg sau image/service được truyền thẳng vào `src.main`.

**Cách A — `docker compose exec` (container `app` đang sleep)**

```bash
docker compose exec app python -m src.main --crawl \
  -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1,2,3

docker compose exec app python -m src.main --analyze --limit 10

docker compose exec app python -m src.main --notify --min-score 70

# Full pipeline một lệnh
docker compose exec app python -m src.main --crawl --analyze --notify \
  -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1,2,3
```

**Cách B — one-shot service `pipeline` (dùng ENTRYPOINT, không cần exec)**

```bash
docker compose run --rm pipeline --crawl --analyze --notify \
  -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1,2,3

docker compose run --rm pipeline --analyze --limit 5
docker compose run --rm pipeline --notify --dry-run
```

**Cách C — `docker compose run app` + override entrypoint**

```bash
docker compose run --rm --entrypoint python app -m src.main --analyze --limit 3
```

### 4. Dừng / xoá

```bash
docker compose down          # giữ volume (DB, model, index)
docker compose down -v       # XOÁ luôn data
```

## Chạy local (không Docker)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

# Ollama
ollama pull phi3:mini

# Postgres qua docker thôi cũng được:
docker compose up -d postgres

cp .env.example .env
# POSTGRES_HOST=localhost , OLLAMA_HOST=http://localhost:11434

python -m src.main --crawl -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1
python -m src.main --analyze --limit 5
python -m src.notification.run_notify --dry-run
```

## Biến môi trường quan trọng

| Biến | Mô tả | Mặc định |
|------|--------|----------|
| `POSTGRES_*` | Kết nối DB | xem `.env.example` |
| `OLLAMA_HOST` | URL Ollama | `http://ollama:11434` |
| `OLLAMA_LLM_MODEL` | Model chat | `phi3:mini` |
| `OLLAMA_NUM_CTX` | Context tokens | `4096` |
| `HF_EMBED_MODEL` | Embedding HF | `paraphrase-multilingual-MiniLM-L12-v2` |
| `NOTIFY_MIN_SCORE` | Ngưỡng gửi mail | `70` |
| `EMAIL_*` / `SMTP_*` | SMTP | — |

## Lưu ý vận hành

### Crawl TopCV & HTTP 429

Site giới hạn tốc độ. Trong `settings.py` nên giữ:

- `CONCURRENT_REQUESTS = 1`
- `DOWNLOAD_DELAY ≈ 1.5–3`
- AutoThrottle bật

### Phân tích nhiều job / OOM

- Chạy theo lô: `--limit 20`, lặp lại (job đã có `ai_analysis` sẽ bỏ qua)
- `run_analysis` dừng sớm sau N lỗi liên tiếp (Ollama chết)
- Model nhỏ (`phi3:mini`, `qwen2.5:0.5b`) phù hợp máy RAM vừa; model lớn cần GPU hoặc RAM cao

### Email Gmail

Dùng **App Password** (bật 2FA), không dùng mật khẩu đăng nhập thường.

### Playwright trong Docker

Image đã cài Chromium headless. Không cần `xvfb` nếu spider chạy headed=False.

## Kiểm tra DB nhanh

```bash
docker compose exec postgres psql -U jobuser -d job_search -c \
  "SELECT job_title, match_score FROM job_listings ORDER BY match_score DESC NULLS LAST LIMIT 10;"
```

## Troubleshooting

| Lỗi | Hướng xử lý |
|-----|-------------|
| `column ... does not exist` | Cập nhật `queries.py` / chạy lại migrate ALTER |
| Ollama OOM / 500 | Giảm `OLLAMA_NUM_CTX`, model nhẹ hơn, `--limit` |
| Không parse JSON | Đã dùng `format=json`; kiểm tra log raw response |
| Embedding đòi OpenAI | Dùng `cv_indexer` HuggingFace, không set OpenAI key |
| Scrapy “no active project” | Chạy từ thư mục có `scrapy.cfg` hoặc qua `src.main --crawl` |
| Email auth fail | App Password + đúng `EMAIL_USER`/`EMAIL_SENDER` |

## License

Dự án cá nhân / học tập. Tôn trọng ToS của các trang tuyển dụng khi crawl.