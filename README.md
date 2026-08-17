# AI Job Search & Analysis Pipeline

Dự án này là một pipeline tự động hóa hoàn chỉnh giúp bạn tìm kiếm, phân tích và sàng lọc các tin tuyển dụng phù hợp nhất với CV của bạn.

## 1. Tổng quan (Overview)

Thay vì phải duyệt thủ công qua nhiều trang web tuyển dụng mỗi ngày, hệ thống này sẽ:
1.  **Tự động thu thập (Crawl)** các tin tuyển dụng từ các trang web được chỉ định.
2.  **Phân tích bằng AI (Analyze)** từng tin tuyển dụng để so sánh với CV của bạn, chấm điểm mức độ phù hợp và đưa ra tóm tắt.
3.  **Gửi báo cáo (Report)** qua email mỗi ngày, liệt kê các công việc phù hợp nhất.

Tất cả được điều phối thông qua một pipeline ETL (Extract, Transform, Load) mạnh mẽ và hiệu quả.

## 2. Công nghệ sử dụng (Tech Stack)

-   **Thu thập dữ liệu:** Scrapy & `scrapy-playwright`
-   **Phân tích AI (RAG):** LlamaIndex
-   **Mô hình ngôn ngữ (LLM):** Ollama (sử dụng model `phi3:mini`)
-   **Cơ sở dữ liệu:** PostgreSQL
-   **Môi trường & Dependencies:** `uv` & Docker
-   **Ngôn ngữ:** Python

## 3. Cấu trúc thư mục (Project Structure)

```
.
├── cv_data/                  # Nơi để chứa file CV.pdf của bạn
├── docker-compose.yml        # Cấu hình cho PostgreSQL và Ollama
├── docs/                     # Tài liệu dự án
├── src/
│   ├── analysis/             # Lõi AI: module tạo index CV và phân tích
│   ├── database/             # Module kết nối và truy vấn DB
│   ├── job_crawler/          # Dự án Scrapy để thu thập dữ liệu
│   ├── notification/         # Module gửi email thông báo
│   └── main.py               # Điểm vào chính, điều phối toàn bộ pipeline
├── .env                      # File chứa các biến môi trường (cần tạo)
└── README.md
```

## 4. Hướng dẫn cài đặt & Cấu hình (Setup)

### Bước 1: Chuẩn bị môi trường

1.  **Clone ays án:**
    ```bash
    git clone <repository_url>
    cd <repository_folder>
    ```

2.  **Tạo file `.env`:**
    Tạo một file tên là `.env` ở thư mục gốc và sao chép nội dung từ file `.env.example` (nếu có) hoặc điền các thông tin sau. Đây là nơi chứa tất cả các cấu hình nhạy cảm.

    ```ini
    # --- Cấu hình PostgreSQL (từ docker-compose.yml) ---
    POSTGRES_DB=job_search
    POSTGRES_USER=user
    POSTGRES_PASSWORD=password
    POSTGRES_HOST=localhost
    POSTGRES_PORT=5432

    # --- Cấu hình SMTP để gửi email ---
    # Ví dụ sử dụng Gmail
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=your_email@gmail.com
    SMTP_PASSWORD=your_gmail_app_password  # Mật khẩu ứng dụng của Gmail
    EMAIL_SENDER=your_email@gmail.com
    EMAIL_RECIPIENT=email_to_receive_report@example.com
    ```
    > **Lưu ý:** Để dùng Gmail, bạn cần tạo một "Mật khẩu ứng dụng". Xem hướng dẫn [tại đây](https://support.google.com/accounts/answer/185833).

3.  **Chạy các dịch vụ nền (PostgreSQL & Ollama):**
    Yêu cầu đã cài đặt Docker và Docker Compose.
    ```bash
    docker-compose up -d
    ```

### Bước 2: Cài đặt Dependencies

1.  **Cài đặt `uv`:**
    Nếu chưa có, hãy cài `uv` theo [hướng dẫn chính thức](https://github.com/astral-sh/uv).

2.  **Cài đặt các gói Python:**
    `uv` sẽ tự động tạo môi trường ảo và cài đặt các gói từ `pyproject.toml`.
    ```bash
    uv pip install -r requirements.txt
    ```
    (Nếu `pyproject.toml` đã được cấu hình đúng, bạn chỉ cần chạy `uv pip sync`)

### Bước 3: Cấu hình AI và CV

1.  **Tải model AI:**
    Chạy lệnh sau để Ollama tải và phục vụ model `phi3:mini`.
    ```bash
    ollama run phi3:mini
    ```
    Chờ đến khi model được tải xong và bạn thấy prompt `>>>`.

2.  **Thêm CV của bạn:**
    Đặt file CV của bạn (định dạng **.pdf**) vào thư mục `cv_data/`. Pipeline sẽ tự động tìm và sử dụng file PDF đầu tiên nó thấy trong thư mục này.

## 5. Chạy Pipeline (Usage)

Sử dụng `src/main.py` làm điểm vào chính. Bạn có thể chạy các phần của pipeline một cách độc lập hoặc chạy toàn bộ.

-   **Chạy toàn bộ pipeline (Crawl -> Analyze -> Report):**
    Đây là lệnh phổ biến nhất để chạy hàng ngày.
    ```bash
    uv run python src/main.py --full-run
    ```

-   **Chỉ thu thập dữ liệu (Crawl):**
    ```bash
    uv run python src/main.py --crawl
    ```

-   **Chỉ phân tích bằng AI (Analyze):**
    Chạy phân tích trên các job đã crawl nhưng chưa được xử lý.
    ```bash
    uv run python src/main.py --analyze
    ```

-   **Chỉ gửi báo cáo (Report):**
    Gửi email báo cáo các job đã được phân tích trong ngày.
    ```bash
    uv run python src/main.py --report
    ```

## 6. Lập lịch chạy hàng ngày (Automation)

Để tự động hóa hoàn toàn, bạn có thể sử dụng bộ lập lịch của hệ điều hành để chạy lệnh `--full-run` mỗi ngày.

### Trên Linux/macOS (sử dụng `cron`)

1.  Mở crontab để chỉnh sửa: `crontab -e`
2.  Thêm dòng sau để chạy pipeline vào 7 giờ sáng mỗi ngày. Thay `/path/to/your/project` bằng đường dẫn tuyệt đối đến thư mục dự án của bạn.

    ```cron
    # Chạy AI Job Search pipeline mỗi 7h sáng
    0 7 * * * cd /path/to/your/project && /path/to/your/uv run python src/main.py --full-run >> /path/to/your/project/cron.log 2>&1
    ```
    > **Lưu ý:** Bạn cần cung cấp đường dẫn đầy đủ đến `uv` nếu nó không nằm trong PATH của cron.

### Trên Windows (sử dụng `Task Scheduler`)

1.  Mở **Task Scheduler**.
2.  Nhấn **Create Basic Task...**
3.  **Name:** Đặt tên là "AI Job Search Daily Run".
4.  **Trigger:** Chọn "Daily" và đặt thời gian bạn muốn chạy (ví dụ: 7:00:00 AM).
5.  **Action:** Chọn "Start a program".
6.  **Program/script:** Điền đường dẫn tuyệt đối đến `uv.exe`.
7.  **Add arguments (optional):**
    ```
    run python src/main.py --full-run
    ```
8.  **Start in (optional):** Điền đường dẫn tuyệt đối đến thư mục dự án của bạn.
9.  Hoàn tất và lưu lại.

---
Chúc may mắn trong hành trình tìm việc!
