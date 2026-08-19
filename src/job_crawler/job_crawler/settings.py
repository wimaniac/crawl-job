# Scrapy settings for job_crawler project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

import os
from dotenv import load_dotenv

# Tải các biến môi trường từ file .env ở thư mục gốc của dự án
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))

BOT_NAME = "job_crawler"

SPIDER_MODULES = ["job_crawler.spiders"]
NEWSPIDER_MODULE = "job_crawler.spiders"

# BẮT BUỘC với scrapy-playwright: nếu thiếu dòng này, download handler
# của Playwright sẽ không được cài đặt đúng và mọi request "playwright": True
# có thể fail âm thầm hoặc rơi vào default handler.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Log rõ ràng để dễ debug. DEBUG rất tốn I/O vì scrapy-playwright log từng
# request/response/CDP frame — chỉ bật khi thật sự cần debug, còn lại dùng INFO.
LOG_LEVEL = os.getenv("SCRAPY_LOG_LEVEL", "INFO")


# Crawl responsibly by identifying yourself (and your website) on the user-agent
#USER_AGENT = "job_crawler (+http://www.yourdomain.com)"

# Obey robots.txt rules
ROBOTSTXT_OBEY = False # Thay đổi thành False vì nhiều trang tuyển dụng chặn crawler

# -- Cấu hình Scrapy-Playwright --
# Kích hoạt download handler của Playwright
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

# Chỉ định loại trình duyệt
PLAYWRIGHT_BROWSER_TYPE = "chromium"

# Cấu hình các tham số khởi động trình duyệt để tối ưu tài nguyên
# QUAN TRỌNG: headless=False + slow_mo=50 là nguyên nhân chính gây chậm.
# slow_mo cộng thêm 50ms vào MỖI lệnh Playwright (mỗi query_selector, click,
# inner_text...) — với ~25-30 lệnh/job-card thì chỉ riêng slow_mo đã tốn
# 1.2-1.5s/card, chưa kể chi phí render GUI khi headless=False.
# Đặt PLAYWRIGHT_HEADLESS=false trong .env khi cần debug trực quan.
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false",
    "slow_mo": int(os.getenv("PLAYWRIGHT_SLOW_MO", "0")),
    "args": [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-software-rasterizer",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--safebrowsing-disable-auto-update",
        # KHÔNG dùng --single-process (gây crash khi ≥2 page)
    ],
}

# Giới hạn số page Playwright mở đồng thời trong 1 context
# (mặc định = CONCURRENT_REQUESTS → dễ OOM / TargetClosedError)
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 2

# Timeout navigation mặc định (ms) — tránh treo quá lâu
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 45000

# User-Agent thật của Chrome thay vì UA mặc định của Playwright (thường lộ rõ
# là automation) — giúp giảm khả năng bị chặn bởi các site chỉ chặn dựa trên
# UA đơn giản. Không giúp vượt qua Cloudflare challenge (topcv.vn), nhưng vô
# hại và có lợi cho các site kiểm tra ít gắt hơn.
DEFAULT_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# Chặn tải các tài nguyên không cần thiết để tiết kiệm băng thông và RAM
PLAYWRIGHT_ABORT_REQUEST_MIME_TYPES = [
    "image",
    "stylesheet",
    "font",
    "media",
    # "script", # Cẩn thận khi chặn script, có thể làm hỏng trang
]

# LƯU Ý: đã bỏ PLAYWRIGHT_CONTEXTS ở đây. Với scrapy-playwright==0.0.48,
# các key trong "default" được truyền thẳng vào browser.new_context(), và
# key "persistent" KHÔNG được API này chấp nhận -> gây lỗi
# "TypeError: Browser.new_context() got an unexpected keyword argument 'persistent'"
# ngay khi khởi tạo context, khiến mọi request fail tức thì (0 item, chạy <1s).
# Không cần khai báo gì thêm: mặc định scrapy-playwright đã tái sử dụng
# 1 context tên "default" dùng chung cho các request cùng context, không
# lưu (persist) ra đĩa trừ khi bạn tự chỉ định user_data_dir.


# -- Tối ưu hiệu suất--
CONCURRENT_REQUESTS = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Tự động điều chỉnh tốc độ crawl để tránh làm quá tải server
AUTOTHROTTLE_ENABLED = True


# Giới hạn bộ nhớ, tự động dừng nếu vượt quá 2GB RAM
MEMUSAGE_LIMIT_MB = 2048
MEMUSAGE_ENABLED = True
MEMUSAGE_NOTIFY_MAIL = [os.getenv("EMAIL_RECIPIENT")] # Gửi cảnh báo đến email của bạn

# -- Cấu hình Item Pipeline --
# Kích hoạt pipeline để xử lý và lưu dữ liệu vào PostgreSQL
ITEM_PIPELINES = {
   "job_crawler.pipelines.PostgresPipeline": 300,
}

# Request headers
#DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
#}

# Spider middlewares
#SPIDER_MIDDLEWARES = {
#    "job_crawler.middlewares.JobCrawlerSpiderMiddleware": 543,
#}

# Downloader middlewares
#DOWNLOADER_MIDDLEWARES = {
#    "job_crawler.middlewares.JobCrawlerDownloaderMiddleware": 543,
#}

# Extensions
#EXTENSIONS = {
#    "scrapy.extensions.telnet.TelnetConsole": None,
#}

# Add some randomness to download delays
RANDOMIZE_DOWNLOAD_DELAY = True
DOWNLOAD_DELAY = 1.5

AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# Cấu hình database từ biến môi trường
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", 5432)
POSTGRES_DB = os.getenv("POSTGRES_DB", "job_search")
POSTGRES_USER = os.getenv("POSTGRES_USER", "user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")