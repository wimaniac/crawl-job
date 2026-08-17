# KẾ HOẠCH DỰ ÁN: AI JOB SEARCH & ANALYSIS PIPELINE

## 1. Tổng quan dự án (Project Overview)
* **Tên dự án:** AI Job Search & Analysis Pipeline
* **Bài toán:** Tự động hóa quy trình tìm kiếm, phân tích và sàng lọc các tin tuyển dụng hàng ngày. Thay vì duyệt thủ công nhiều trang web, hệ thống sẽ tự động thu thập tin tức, sử dụng mô hình ngôn ngữ (LLM) để phân tích mức độ phù hợp của từng công việc với một CV (định dạng PDF) được cung cấp, và gửi báo cáo tóm tắt qua email.
* **Mục tiêu:** Xây dựng một pipeline ETL (Extract, Transform, Load) vững chắc, hiệu quả về tài nguyên, có khả năng mở rộng để thu thập dữ liệu từ nhiều nguồn và cung cấp các phân tích chất lượng cao.
* **Kết quả đầu ra:** Email báo cáo hàng ngày liệt kê các công việc phù hợp nhất, kèm theo các thông tin chính như `job_title`, `salary_range`, `location`, `url` và tóm tắt phân tích của AI.

---

## 2. Kiến trúc & Công nghệ (Architecture & Technology Stack)

1.  **Thu thập dữ liệu (Crawling - Extract):**
    *   **Framework:** **Scrapy** kết hợp với plugin **`scrapy-playwright`**.
    *   **Chiến lược:**
        *   Các trang web tĩnh hoặc có API: Dùng request gốc của Scrapy để đạt hiệu suất cao.
        *   Các trang yêu cầu JavaScript (JS-rendered): Giao cho Playwright mở trình duyệt nền để xử lý.
    *   **Tối ưu tài nguyên (Quan trọng với 16GB RAM, RTX 3050 8GB VRAM):** Cấu hình chặt chẽ trong `settings.py` để phù hợp với tài nguyên hệ thống, tập trung vào:
        1.  **Giới hạn số lượng Trình duyệt & Tab chạy song song:**
            *   Chỉ định `CONCURRENT_REQUESTS` vừa phải (ví dụ: `8`) trong `settings.py` để tránh quá tải RAM, đặc biệt khi mỗi request mở một tab Playwright.
            *   **Tái sử dụng Browser Context:** Cấu hình Playwright để dùng chung `browser_context` giữa các request, giảm chi phí khởi tạo trình duyệt mới.
        2.  **Chặn các tài nguyên không cần thiết (Resource Blocking):**
            *   Chặn request media: Thiết lập `PLAYWRIGHT_ABORT_REQUEST_MIME_TYPES` hoặc cấu hình route để hủy toàn bộ request tải ảnh, stylesheet, font, media, quảng cáo... Điều này giúp tiết kiệm CPU/RAM đáng kể.
            *   Tắt GPU Acceleration: Thêm flag `--disable-gpu` vào `PLAYWRIGHT_LAUNCH_OPTIONS`.
        3.  **Đóng Tab/Page ngay sau khi cào xong:**
            *   Đảm bảo mỗi Page (Tab trình duyệt) sau khi trích xuất dữ liệu xong phải được giải phóng bộ nhớ ngay lập tức. Cấu hình `playwright_page_coroutines` với `close=True` để tránh rò rỉ bộ nhớ.
        4.  **Tắt Giao diện (Headless Mode) & Tối ưu tham số Trình duyệt:**
            *   **Bắt buộc dùng `headless=True`:** Chạy trình duyệt ẩn, không render giao diện đồ họa.
            *   **Thêm Chromium Flags tiết kiệm bộ nhớ:** Pass các tham số sau vào cấu hình `PLAYWRIGHT_LAUNCH_OPTIONS`: `--no-sandbox`, `--disable-setuid-sandbox`, `--disable-dev-shm-usage`, `--single-process` hoặc `--no-zygote`.
        5.  **Quản lý Bộ nhớ & Tự động Restart theo chu kỳ:**
            *   Giới hạn số request trên mỗi Browser instance: Cấu hình để Playwright tự động đóng và khởi động lại trình trình duyệt sau khi xử lý khoảng `100 - 200` request để tránh rò rỉ bộ nhớ.
            *   **Đặt hạn ngạch tài nguyên (Memory Limit):** Kích hoạt extension `scrapy.extensions.memusage.MemoryUsage` của Scrapy để tự động dừng hoặc cảnh báo khi tiến trình Scrapy vượt quá dung lượng RAM cho phép (ví dụ: tối đa `2GB` RAM).

2.  **Xử lý & Phân tích (Transform):**
    *   **Framework:** **LlamaIndex** để xây dựng pipeline RAG (Retrieval-Augmented Generation).
    *   **Quy trình:**
        1.  **Indexing:** CV của người dùng (PDF) sẽ được đọc và chuyển thành một "chỉ mục kiến thức" (Vector Index) để AI có thể tìm kiếm và truy vấn hiệu quả.
        2.  **Retrieval:** Với mỗi Mô tả Công việc (JD), hệ thống sẽ dùng JD để truy vấn vào Index CV, tìm ra các phần kinh nghiệm/kỹ năng liên quan nhất.
        3.  **Synthesis:** Chỉ những thông tin liên quan được trích xuất cùng với JD sẽ được đưa vào prompt và gửi đến model AI.
    *   **Mô hình AI:** **Ollama** phục vụ model **`phi4-mini`**, được tích hợp thông qua `LlamaIndex`.
    *   **Triển khai:** Ollama chạy trong một Docker container riêng.

3.  **Lưu trữ (Load):**
    *   **Cơ sở dữ liệu:** **PostgreSQL**.
    *   **Driver:** **`asyncpg`** để thực hiện các thao tác ghi/đọc bất đồng bộ.

4.  **Thông báo (Notification):**
    *   **Kênh:** **Email**.
    *   **Nội dung:** Báo cáo HTML được định dạng rõ ràng, dễ đọc.

5.  **Quản lý dự án:**
    *   **Môi trường:** **`uv`** để quản lý môi trường ảo và các gói phụ thuộc.
    *   **Biến môi trường:** **`python-dotenv`** để quản lý secrets và cấu hình.

---

## 3. Lược đồ dữ liệu (Data Schema)
Bảng `job_listings` trong PostgreSQL sẽ bao gồm các trường chính sau:

*   `id` (Primary Key, Auto-increment)
*   `job_title` (TEXT)
*   `company_name` (TEXT)
*   `location` (TEXT)
*   `salary_range` (TEXT, nullable)
*   `job_url` (TEXT, UNIQUE) - Dùng để khử trùng lặp.
*   `job_description_raw` (TEXT) - Nội dung gốc thu thập được.
*   `match_score` (INTEGER, nullable) - Điểm phù hợp do AI chấm.
*   `ai_analysis` (TEXT, nullable) - Tóm tắt phân tích từ AI.
*   `created_at` (TIMESTAMP, default NOW())

---

## 4. Phân rã công việc (Work Breakdown Structure)

**Giai đoạn 1: Thiết lập nền tảng (Project Setup)**
- [x] Khởi tạo dự án với `uv` (`uv venv`).
- [x] Cài đặt `scrapy`, `scrapy-playwright`, `ollama`, `asyncpg`, `python-dotenv`, `llama-index`.
- [x] Tạo file `docker-compose.yml` định nghĩa service `postgres` và `ollama/ollama`.
- [x] Viết script Python dùng `asyncpg` để kết nối và khởi tạo bảng `job_listings` nếu chưa tồn tại.
- [x] Cấu hình file `.env` cho các thông tin nhạy cảm.

**Giai đoạn 2: Xây dựng bộ thu thập dữ liệu (Crawler Development)**
- [x] Tạo dự án Scrapy (`scrapy startproject job_crawler`).
- [x] Cấu hình `settings.py` với các tham số tối ưu Playwright.
- [ ] Viết một "Spider" chung có khả năng xử lý cả trang tĩnh và động.
- [x] Implement Scrapy Item Pipeline để làm sạch dữ liệu và lưu vào PostgreSQL bằng `asyncpg`.
- [ ] Đảm bảo logic khử trùng lặp bằng `job_url` hoạt động chính xác.

**Giai đoạn 3: Tích hợp lõi AI với LlamaIndex (AI Core Integration)**
- [x] **Xây dựng module quản lý CV Index (`cv_indexer.py`):**
    - [x] Viết hàm sử dụng `LlamaIndex` (`SimplePDFReader`) để đọc file CV.
    - [x] Xây dựng logic tạo `VectorStoreIndex` từ dữ liệu CV.
    - [x] Implement cơ chế lưu (persist) index vào thư mục `storage/cv_index` để không phải tạo lại mỗi lần chạy.
    - [x] Thêm logic kiểm tra ngày sửa đổi của file CV để tự động tạo lại index nếu CV được cập nhật.
- [x] **Xây dựng module phân tích (`analyzer.py`):**
    - [x] Viết lớp hoặc hàm để tải CV index đã có.
    - [x] Tạo một `QueryEngine` từ `LlamaIndex`.
    - [x] Xây dựng một prompt template hiệu quả cho việc phân tích sự phù hợp.
    - [x] Viết hàm nhận đầu vào là một JD, dùng `QueryEngine` để truy vấn và nhận về `match_score` và `ai_analysis`.
- [x] **Tích hợp vào pipeline chính:**
    - [x] Viết script điều phối (`main.py`) để lấy các JD từ DB (sau khi Giai đoạn 2 chạy), lần lượt đưa qua module phân tích, và cập nhật kết quả AI vào lại DB.

**Giai đoạn 4: Hoàn thiện và Tự động hóa (Finalizing & Automation)**
- [ ] Viết module (`email_notifier.py`) sử dụng `smtplib` để gửi email.
- [ ] Tạo hàm truy vấn DB lấy các job có điểm số cao nhất trong ngày.
- [ ] Định dạng kết quả thành một email HTML đẹp mắt.
- [ ] Thiết lập bộ lập lịch (ví dụ: `APScheduler` trong `main.py` hoặc Cron job của hệ thống) để chạy toàn bộ pipeline mỗi ngày.

---

## 5. Kế hoạch kiểm thử (Testing Plan)
*   **Crawler:** Chạy thử spider trên ít nhất 1 trang tĩnh và 1 trang động.
*   **Resource Management:** Theo dõi mức sử dụng RAM/CPU khi crawler và indexing chạy.
*   **Database:** Kiểm tra logic ghi dữ liệu và chống trùng lặp.
*   **AI Model:** Đánh giá chất lượng output từ pipeline RAG của `LlamaIndex` với các JD có format khác nhau.
*   **End-to-End:** Chạy toàn bộ pipeline và xác nhận email cuối cùng chứa dữ liệu chính xác.
