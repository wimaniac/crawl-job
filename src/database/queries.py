# src/database/queries.py
import logging
from .connection import DatabaseConnection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def initialize_database():
    """
    Khởi tạo cơ sở dữ liệu: tạo bảng `job_listings` nếu nó chưa tồn tại.
    """
    create_table_query = """
    CREATE TABLE IF NOT EXISTS job_listings (
        id SERIAL PRIMARY KEY,
        job_title TEXT,
        company_name TEXT,
        location TEXT,
        salary_range TEXT,
        job_url TEXT UNIQUE,
        job_description_raw TEXT,
        match_score INTEGER,
        ai_analysis TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        async with DatabaseConnection() as conn:
            await conn.execute(create_table_query)
        logging.info("Bảng 'job_listings' đã được kiểm tra và sẵn sàng.")
    except Exception as e:
        logging.error(f"Lỗi khi khởi tạo bảng 'job_listings': {e}")
        raise

async def get_unanalyzed_jobs():
    """
    Truy vấn và trả về danh sách các công việc chưa được AI phân tích.
    """
    query = "SELECT id, job_description_raw FROM job_listings WHERE ai_analysis IS NULL;"
    try:
        async with DatabaseConnection() as conn:
            records = await conn.fetch(query)
            logging.info(f"Tìm thấy {len(records)} công việc chưa được phân tích.")
            return records
    except Exception as e:
        logging.error(f"Lỗi khi lấy các công việc chưa được phân tích: {e}")
        return []

async def update_job_with_analysis(job_id: int, match_score: int, ai_analysis: str):
    """
    Cập nhật một tin tuyển dụng với kết quả phân tích của AI.
    """
    query = """
    UPDATE job_listings
    SET match_score = $1, ai_analysis = $2
    WHERE id = $3;
    """
    try:
        async with DatabaseConnection() as conn:
            await conn.execute(query, match_score, ai_analysis, job_id)
            logging.info(f"Đã cập nhật kết quả phân tích cho job ID {job_id}.")
    except Exception as e:
        logging.error(f"Lỗi khi cập nhật job ID {job_id}: {e}")

async def get_best_matching_jobs(score_threshold: int = 70, days_limit: int = 1):
    """
    Lấy các công việc phù hợp nhất dựa trên điểm số và ngày tạo.

    Args:
        score_threshold (int): Ngưỡng điểm tối thiểu để một công việc được xem là phù hợp.
        days_limit (int): Giới hạn số ngày trở lại để tìm kiếm công việc.

    Returns:
        Một danh sách các record công việc phù hợp nhất.
    """
    query = """
    SELECT job_title, company_name, location, salary_range, job_url, match_score, ai_analysis
    FROM job_listings
    WHERE match_score >= $1
      AND created_at >= NOW() - ($2 * INTERVAL '1 day')
    ORDER BY match_score DESC;
    """
    try:
        async with DatabaseConnection() as conn:
            records = await conn.fetch(query, score_threshold, days_limit)
            logging.info(f"Tìm thấy {len(records)} công việc phù hợp (điểm >= {score_threshold}) trong {days_limit} ngày qua.")
            return records
    except Exception as e:
        logging.error(f"Lỗi khi lấy các công việc phù hợp nhất: {e}")
        return []

# Các hàm khác để tương tác với DB sẽ được thêm vào đây
# Ví dụ: hàm thêm một tin tuyển dụng mới
# async def add_job_listing(job_data):
#     ...
