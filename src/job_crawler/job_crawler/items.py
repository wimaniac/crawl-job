# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class JobListingItem(scrapy.Item):
    """
    Định nghĩa cấu trúc dữ liệu cho một tin tuyển dụng.
    Các trường này tương ứng với các cột trong bảng 'job_listings' của PostgreSQL.
    """
    job_title = scrapy.Field()
    company_name = scrapy.Field()
    location = scrapy.Field()
    salary_range = scrapy.Field()
    experience = scrapy.Field()
    job_url = scrapy.Field()

    # Tách mô tả thành các phần riêng (theo panel TopCV)
    job_description = scrapy.Field()      # Mô tả công việc
    job_requirements = scrapy.Field()     # Yêu cầu ứng viên
    tech_stack = scrapy.Field()           # Tech stack (nếu có)
    job_benefits = scrapy.Field()         # Quyền lợi

    # Field tổng hợp để AI pipeline (ghép từ các phần trên)
    job_description_raw = scrapy.Field()