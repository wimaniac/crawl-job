import logging
from .connection import DatabaseConnection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def initialize_database():
    """Tạo bảng job_listings nếu chưa có + ALTER cột mới an toàn."""
    create_table_query = """
    CREATE TABLE IF NOT EXISTS job_listings (
        id SERIAL PRIMARY KEY,
        job_title TEXT,
        company_name TEXT,
        location TEXT,
        salary_range TEXT,
        experience TEXT,
        job_url TEXT UNIQUE,
        job_description TEXT,
        job_requirements TEXT,
        job_benefits TEXT,
        match_score INTEGER,
        ai_analysis TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    alters = [
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS experience TEXT",
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_description TEXT",
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_requirements TEXT",
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_benefits TEXT",
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS match_score INTEGER",
        "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS ai_analysis TEXT",
    ]
    try:
        async with DatabaseConnection() as conn:
            await conn.execute(create_table_query)
            for stmt in alters:
                await conn.execute(stmt)
        logging.info("Bảng 'job_listings' đã sẵn sàng.")
    except Exception as e:
        logging.error(f"Lỗi khi khởi tạo bảng 'job_listings': {e}")
        raise


async def get_unanalyzed_jobs(limit: int | None = None):
    """Lấy job chưa có ai_analysis và còn nội dung mô tả."""
    query = """
    SELECT id, job_title, company_name, location, salary_range, experience,
           job_description, job_requirements, job_benefits, job_url
    FROM job_listings
    WHERE ai_analysis IS NULL
      AND (
            COALESCE(job_description, '') <> ''
         OR COALESCE(job_requirements, '') <> ''
         OR COALESCE(job_benefits, '') <> ''
      )
    ORDER BY id
    """
    if limit and limit > 0:
        query += f" LIMIT {int(limit)}"
    try:
        async with DatabaseConnection() as conn:
            records = await conn.fetch(query)
            logging.info(f"Tìm thấy {len(records)} công việc chưa phân tích.")
            return records
    except Exception as e:
        logging.error(f"Lỗi get_unanalyzed_jobs: {e}")
        return []


async def update_job_with_analysis(job_id: int, match_score: int, ai_analysis: str):
    query = """
    UPDATE job_listings
    SET match_score = $1, ai_analysis = $2
    WHERE id = $3;
    """
    try:
        async with DatabaseConnection() as conn:
            await conn.execute(query, match_score, ai_analysis, job_id)
            logging.info(f"Đã cập nhật phân tích job id={job_id} score={match_score}")
    except Exception as e:
        logging.error(f"Lỗi update job id={job_id}: {e}")


async def get_best_matching_jobs(score_threshold: int = 70, days_limit: int = 7):
    query = """
    SELECT job_title, company_name, location, salary_range, job_url,
           match_score, ai_analysis, created_at
    FROM job_listings
    WHERE match_score >= $1
      AND created_at >= NOW() - ($2 * INTERVAL '1 day')
    ORDER BY match_score DESC;
    """
    try:
        async with DatabaseConnection() as conn:
            records = await conn.fetch(query, score_threshold, days_limit)
            logging.info(
                f"Tìm thấy {len(records)} job phù hợp "
                f"(score>={score_threshold}, {days_limit} ngày)."
            )
            return records
    except Exception as e:
        logging.error(f"Lỗi get_best_matching_jobs: {e}")
        return []