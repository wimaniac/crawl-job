# Cấu trúc thư mục dự án: AI Job Search & Analysis Pipeline

Cấu trúc thư mục được thiết kế để phân tách rõ ràng các thành phần của pipeline: thu thập dữ liệu, phân tích AI, tương tác cơ sở dữ liệu và thông báo.

```
job_search/
│
├── .env                  # (Local) File chứa biến môi trường (DB, email, etc.)
├── .gitignore
├── docker-compose.yml    # Định nghĩa service cho postgres và ollama
├── README.md             # Hướng dẫn tổng quan dự án
├── pyproject.toml        # Quản lý môi trường và các gói phụ thuộc bởi `uv`
│
├── storage/              # <<< MỚI: Chứa dữ liệu, index được tạo ra
│   └── cv_index/         #      (Nên thêm vào .gitignore)
│
└── src/
    │
    ├── __init__.py
    ├── main.py             # Entry point chính, điều phối toàn bộ pipeline
    │
    ├── ai_core/            # <<< MỚI: Chứa toàn bộ logic LlamaIndex
    │   ├── __init__.py
    │   ├── analyzer.py     #       (Tạo QueryEngine, phân tích JD so với CV)
    │   └── cv_indexer.py   #       (Tạo, tải, và lưu trữ CV Index)
    │
    ├── core/               # Chứa các cấu hình và client cơ bản
    │   ├── __init__.py
    │   └── config.py       #       (Tải cấu hình từ .env)
    │
    ├── database/
    │   ├── __init__.py
    │   ├── connection.py     # Quản lý connection pool với asyncpg
    │   └── queries.py        # Chứa các câu lệnh SQL và hàm tương tác DB
    │
    ├── notification/
    │   ├── __init__.py
    │   └── email_notifier.py # Module gửi email thông báo
    │
    └── job_crawler/          # <<< DỰ ÁN SCRAPY (giữ nguyên)
        ├── scrapy.cfg
        └── job_crawler/
            ├── __init__.py
            ├── spiders/
            │   └── generic_job_spider.py
            ├── items.py
            ├── middlewares.py
            ├── pipelines.py
            └── settings.py
```

### Giải thích cấu trúc mới

*   **`src/ai_core/` (Lõi AI mới):** Đây là sự thay đổi lớn nhất. Thư mục này thay thế cho `parsers/` và `core/llm_client.py` cũ.
    *   `cv_indexer.py`: Chịu trách nhiệm duy nhất cho việc xử lý CV. Nó sẽ đọc file PDF, tạo và quản lý việc lưu/tải index. Logic kiểm tra CV có cần cập nhật hay không sẽ nằm ở đây.
    *   `analyzer.py`: Sẽ sử dụng index do `cv_indexer` tạo ra. Nó khởi tạo một `QueryEngine` của LlamaIndex và thực hiện việc phân tích mỗi JD để cho ra điểm số và tóm tắt.
*   **`storage/` (Nơi lưu trữ Index):** Chúng ta tách biệt phần code (`src`) và phần dữ liệu được tạo ra (`storage`). Thư mục này sẽ chứa index của CV. Việc này giúp `src` luôn sạch sẽ và chỉ chứa mã nguồn. Thư mục `storage` nên được thêm vào file `.gitignore` để không commit index lên Git.
*   **`src/core/config.py` (Tinh gọn):** Vai trò của thư mục `core` giờ đây chỉ còn là quản lý cấu hình chung của dự án.
*   **Các thành phần khác giữ nguyên:** Các module `database`, `notification`, và toàn bộ dự án `job_crawler` Scrapy vẫn giữ nguyên vai trò và cấu trúc của chúng.

Cấu trúc mới này giúp phân tách vai trò rõ ràng hơn, phù hợp với kiến trúc pipeline RAG: một module lo việc "học" tài liệu (indexing), một module lo việc "hỏi-đáp" (analysis).
