# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html

import asyncpg
from scrapy.exceptions import NotConfigured


class PostgresPipeline:
    """
    Scrapy pipeline lưu Item vào PostgreSQL (async với asyncpg).
    Tự tạo bảng + thêm cột mới nếu thiếu (ALTER TABLE an toàn).
    """

    def __init__(self, db_settings):
        self.db_settings = db_settings
        self.pool = None

    @classmethod
    def from_crawler(cls, crawler):
        db_settings = {
            "host": crawler.settings.get("POSTGRES_HOST"),
            "port": crawler.settings.get("POSTGRES_PORT"),
            "database": crawler.settings.get("POSTGRES_DB"),
            "user": crawler.settings.get("POSTGRES_USER"),
            "password": crawler.settings.get("POSTGRES_PASSWORD"),
        }
        if not all(db_settings.values()):
            raise NotConfigured(
                "Thiếu thông tin cấu hình PostgreSQL. Kiểm tra .env và settings.py."
            )
        return cls(db_settings)

    async def open_spider(self, spider):
        spider.logger.info("Mở kết nối đến PostgreSQL.")
        try:
            self.pool = await asyncpg.create_pool(**self.db_settings)
            spider.logger.info("Đã tạo connection pool thành công.")
        except Exception as e:
            spider.logger.error(f"Không thể kết nối đến PostgreSQL: {e}")
            raise NotConfigured(f"Lỗi kết nối PostgreSQL: {e}")

        # Tạo bảng nếu chưa có
        create_table_sql = """
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
            tech_stack TEXT,
            job_benefits TEXT,
            job_description_raw TEXT,
            match_score INTEGER,
            ai_analysis TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        # Thêm cột mới nếu bảng cũ đã tồn tại (không phá dữ liệu cũ)
        alter_columns = [
            "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS experience TEXT",
            "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_description TEXT",
            "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_requirements TEXT",
            "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS tech_stack TEXT",
            "ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS job_benefits TEXT",
        ]
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_sql)
                for stmt in alter_columns:
                    await conn.execute(stmt)
            spider.logger.info("Bảng 'job_listings' đã sẵn sàng.")
        except Exception as e:
            spider.logger.error(f"Không thể tạo/cập nhật bảng job_listings: {e}")
            raise NotConfigured(f"Lỗi khởi tạo bảng: {e}")

    async def close_spider(self, spider):
        if self.pool:
            spider.logger.info("Đóng kết nối PostgreSQL.")
            await self.pool.close()

    async def process_item(self, item, spider):
        if not self.pool:
            spider.logger.error("Connection pool không tồn tại, không thể xử lý item.")
            return item

        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    """
                    INSERT INTO job_listings (
                        job_title, company_name, location, salary_range, experience,
                        job_url, job_description, job_requirements, tech_stack,
                        job_benefits, job_description_raw
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (job_url) DO UPDATE SET
                        job_title = EXCLUDED.job_title,
                        company_name = EXCLUDED.company_name,
                        location = EXCLUDED.location,
                        salary_range = EXCLUDED.salary_range,
                        experience = EXCLUDED.experience,
                        job_description = EXCLUDED.job_description,
                        job_requirements = EXCLUDED.job_requirements,
                        tech_stack = EXCLUDED.tech_stack,
                        job_benefits = EXCLUDED.job_benefits,
                        job_description_raw = EXCLUDED.job_description_raw
                    ;
                    """,
                    item.get("job_title"),
                    item.get("company_name"),
                    item.get("location"),
                    item.get("salary_range"),
                    item.get("experience"),
                    item.get("job_url"),
                    item.get("job_description"),
                    item.get("job_requirements"),
                    item.get("tech_stack"),
                    item.get("job_benefits"),
                    item.get("job_description_raw"),
                )
                spider.logger.info(f"Đã lưu job: {item.get('job_title')}")
            except Exception as e:
                spider.logger.error(
                    f"Lỗi khi lưu item vào DB: {e} | title={item.get('job_title')}"
                )

        return item