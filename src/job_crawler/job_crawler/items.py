import scrapy


class JobListingItem(scrapy.Item):
    """
    Cấu trúc dữ liệu tin tuyển dụng — map với bảng job_listings.
    """
    job_title = scrapy.Field()
    company_name = scrapy.Field()
    location = scrapy.Field()
    salary_range = scrapy.Field()
    experience = scrapy.Field()
    job_url = scrapy.Field()

    job_description = scrapy.Field()      # Mô tả công việc
    job_requirements = scrapy.Field()     # Yêu cầu ứng viên
    job_benefits = scrapy.Field()         # Quyền lợi