# src/notification/email_notifier.py
import html
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _esc(value) -> str:
    """Escape HTML an toàn cho dữ liệu lấy từ crawl (có thể chứa <, >, &...)."""
    return html.escape(str(value)) if value is not None else ""


def format_jobs_to_html(jobs: list) -> str:
    """
    Định dạng một danh sách các công việc thành một chuỗi HTML đẹp mắt.
    """
    if not jobs:
        return "<p>Hôm nay không tìm thấy công việc mới nào phù hợp.</p>"

    # CSS cho email
    html_style = """
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { width: 90%; max-width: 800px; margin: 20px auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }
        .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; }
        .job { padding: 20px; border-bottom: 1px solid #eee; }
        .job:last-child { border-bottom: none; }
        .job h2 { margin-top: 0; color: #4CAF50; }
        .job-meta { font-size: 0.9em; color: #777; }
        .job-analysis { background-color: #f9f9f9; border-left: 4px solid #4CAF50; padding: 15px; margin-top: 15px; border-radius: 4px; }
        .footer { background-color: #f2f2f2; color: #777; padding: 15px; text-align: center; font-size: 0.8em; }
        .score { font-weight: bold; color: #E65100; }
    </style>
    """

    # Bắt đầu xây dựng HTML
    html_content = "<html><head>" + html_style + "</head><body>"
    html_content += '<div class="container">'
    html_content += f'<div class="header"><h1>Báo cáo việc làm ngày {datetime.now().strftime("%d-%m-%Y")}</h1></div>'

    for job in jobs:
        # .get() an toàn — job thiếu field (NULL trong DB) không làm crash;
        # escape mọi giá trị lấy từ crawl để tránh vỡ layout / HTML injection.
        job_url = _esc(job.get("job_url") or "#")
        job_title = _esc(job.get("job_title") or "(Không có tiêu đề)")
        company_name = _esc(job.get("company_name") or "N/A")
        location = _esc(job.get("location") or "N/A")
        salary_range = _esc(job.get("salary_range") or "N/A")
        match_score = _esc(job.get("match_score") if job.get("match_score") is not None else "N/A")
        ai_analysis = _esc(job.get("ai_analysis") or "Chưa có phân tích.")

        html_content += f"""
        <div class="job">
            <h2><a href="{job_url}">{job_title}</a></h2>
            <div class="job-meta">
                <span><strong>Công ty:</strong> {company_name}</span><br>
                <span><strong>Địa điểm:</strong> {location}</span><br>
                <span><strong>Lương:</strong> {salary_range}</span>
            </div>
            <div class="job-analysis">
                <p><strong>Đánh giá của AI:</strong> <span class="score">Điểm phù hợp: {match_score}/100</span></p>
                <p>{ai_analysis}</p>
            </div>
        </div>
        """
    
    html_content += '<div class="footer"><p>Báo cáo này được tạo tự động bởi AI Job Search Pipeline.</p></div>'
    html_content += "</div></body></html>"
    
    return html_content

def send_email(subject: str, html_content: str) -> bool:
    """
    Gửi email sử dụng các cấu hình từ biến môi trường.
    Trả về True nếu gửi thành công, False nếu thất bại — QUAN TRỌNG: caller
    (vd run_notify.py) cần biết chắc để quyết định có đánh dấu job "đã gửi"
    hay không. Nếu gửi lỗi mà vẫn đánh dấu đã gửi, job đó sẽ "biến mất"
    khỏi các lần gửi sau dù người dùng chưa từng nhận được.
    """
    # Lấy cấu hình từ .env. Ưu tiên SMTP_* nếu có, fallback về EMAIL_* để tương thích ngược.
    sender_email = os.getenv("EMAIL_SENDER")
    receiver_email = os.getenv("EMAIL_RECIPIENT")
    smtp_server = os.getenv("SMTP_HOST") or os.getenv("EMAIL_HOST")
    smtp_port = int(os.getenv("SMTP_PORT") or os.getenv("EMAIL_PORT") or 587)
    smtp_user = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
    smtp_password = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASSWORD")

    # Kiểm tra các biến môi trường cần thiết
    required_vars = [sender_email, receiver_email, smtp_server, smtp_port, smtp_user, smtp_password]
    if not all(required_vars):
        logging.error("Thiếu thông tin cấu hình SMTP trong file .env. Không thể gửi email.")
        logging.error(f"Kiểm tra các biến: EMAIL_SENDER, EMAIL_RECIPIENT, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD")
        return False

    # Tạo đối tượng email
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = receiver_email

    # Đính kèm nội dung HTML
    message.attach(MIMEText(html_content, "html"))

    # Gửi email
    try:
        logging.info(f"Đang kết nối đến server SMTP: {smtp_server}:{smtp_port}...")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Kích hoạt bảo mật
            logging.info("Đang đăng nhập...")
            server.login(smtp_user, smtp_password)
            logging.info(f"Đang gửi email đến {receiver_email}...")
            server.sendmail(sender_email, receiver_email, message.as_string())
            logging.info("Email đã được gửi thành công!")
            return True
    except smtplib.SMTPAuthenticationError as e:
        smtp_code = getattr(e, "smtp_code", "?")
        smtp_error = getattr(e, "smtp_error", b"")
        if isinstance(smtp_error, bytes):
            smtp_error = smtp_error.decode("utf-8", errors="replace")
        logging.error(f"Lỗi xác thực SMTP (code={smtp_code}): {smtp_error}")
        logging.error(
            "Với Gmail: từ ~2022 KHÔNG dùng được mật khẩu đăng nhập thường "
            "cho SMTP nữa, kể cả đúng mật khẩu vẫn bị từ chối. Cần: "
            "(1) bật 2-Step Verification cho tài khoản Google, "
            "(2) tạo 'Mật khẩu ứng dụng' (App Password) tại "
            "https://myaccount.google.com/apppasswords, dùng chuỗi 16 ký tự "
            "đó làm EMAIL_PASSWORD — không phải mật khẩu Gmail thường. "
            "(3) EMAIL_USER phải trùng khớp EMAIL_SENDER (cùng 1 địa chỉ)."
        )
        return False
    except Exception as e:
        logging.error(f"Đã xảy ra lỗi khi gửi email: {e}")
        return False

if __name__ == '__main__':
    # --- Dành cho việc chạy thử nghiệm ---
    # Cần tạo file .env ở thư mục gốc và điền các biến SMTP
    from pathlib import Path
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    load_dotenv(PROJECT_ROOT / ".env")

    print("Bắt đầu chạy thử nghiệm module `email_notifier`...")

    # 1. Tạo dữ liệu giả
    print("\n--- Bước 1: Tạo dữ liệu công việc giả ---")
    mock_jobs = [
        {
            'job_title': 'Senior Python Developer',
            'company_name': 'TechCorp',
            'location': 'Ho Chi Minh City',
            'salary_range': 'Up to $3000',
            'job_url': 'https://example.com/job1',
            'match_score': 95,
            'ai_analysis': 'Rất phù hợp. Ứng viên có 5 năm kinh nghiệm Python và đã làm việc với các công nghệ ETL, đúng như yêu cầu.'
        },
        {
            'job_title': 'Data Engineer',
            'company_name': 'DataDriven Inc.',
            'location': 'Remote',
            'salary_range': 'Negotiable',
            'job_url': 'https://example.com/job2',
            'match_score': 80,
            'ai_analysis': 'Phù hợp. Kinh nghiệm với PostgreSQL và pipeline dữ liệu của ứng viên là một điểm cộng lớn cho vị trí này.'
        }
    ]
    print(f"Đã tạo {len(mock_jobs)} công việc giả.")

    # 2. Định dạng HTML
    print("\n--- Bước 2: Tạo nội dung email HTML ---")
    html_output = format_jobs_to_html(mock_jobs)
    print("Nội dung HTML đã được tạo. (Xem file 'test_email.html' để kiểm tra)")
    with open("test_email.html", "w", encoding="utf-8") as f:
        f.write(html_output)

    # 3. Gửi email
    print("\n--- Bước 3: Gửi email thử nghiệm ---")
    print("LƯU Ý: Để bước này thành công, bạn cần cấu hình các biến SMTP trong file .env")
    
    subject = f"Báo cáo việc làm hàng ngày - {datetime.now().strftime('%d/%m/%Y')} [Thử nghiệm]"
    send_email(subject, html_output)

    print("\nThử nghiệm module `email_notifier` hoàn tất!")