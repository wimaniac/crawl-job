import argparse
import subprocess
import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Thêm thư mục gốc của dự án vào sys.path để import các module khác
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)

def run_crawler():
    """
    Chạy Scrapy spider để thu thập dữ liệu công việc.
    """
    logging.info("Bắt đầu quá trình thu thập dữ liệu (crawl)...")
    
    # Đường dẫn đến thư mục dự án Scrapy
    crawler_project_path = os.path.join(PROJECT_ROOT, 'job_crawler')
    
    # Lệnh để chạy spider. 'scrapy' phải có trong PATH của môi trường ảo.
    # Chúng ta chạy lệnh từ bên trong thư mục dự án Scrapy.
    command = ["scrapy", "crawl", "generic_job_spider"]

    try:
        # QUAN TRỌNG: KHÔNG dùng capture_output=True ở đây.
        # Scrapy in toàn bộ log hữu ích (số job tìm thấy, có bị robots.txt
        # chặn không, lỗi selector, lỗi Playwright...) ra stdout/stderr.
        # Nếu capture rồi chỉ in lại qua logging.debug(), log đó sẽ bị
        # nuốt mất khi logging.basicConfig ở mức INFO — khiến ta không
        # thấy gì kể cả khi crawl "thành công" nhưng thu được 0 item.
        # Để capture_output=False (mặc định), output của subprocess sẽ
        # stream thẳng ra terminal theo thời gian thực.
        # `cwd` (current working directory) rất quan trọng để Scrapy tìm thấy file scrapy.cfg
        process = subprocess.run(command, cwd=crawler_project_path, check=True, text=True)
        logging.info("Quá trình thu thập dữ liệu hoàn tất.")
    except FileNotFoundError:
        logging.error("Lỗi: Lệnh 'scrapy' không được tìm thấy. Hãy đảm bảo bạn đã kích hoạt môi trường ảo (`.venv`) và Scrapy đã được cài đặt.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Quá trình Scrapy spider gặp lỗi. Return code: {e.returncode}")

def main():
    parser = argparse.ArgumentParser(description="AI Job Search & Analysis Pipeline")
    parser.add_argument('--crawl', action='store_true', help='Chỉ chạy tác vụ thu thập dữ liệu (crawling).')
    
    args = parser.parse_args()
    
    if args.crawl:
        run_crawler()
    else:
        print("Vui lòng chỉ định một tác vụ để chạy. Ví dụ: --crawl")
        parser.print_help()

if __name__ == "__main__":
    main()