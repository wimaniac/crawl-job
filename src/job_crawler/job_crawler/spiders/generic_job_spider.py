import json
import os
import re

import scrapy
from scrapy_playwright.page import PageMethod

from job_crawler.items import JobListingItem


class GenericJobSpider(scrapy.Spider):
    """
    Spider tổng quát, đọc config từ sites_config.json.

    Cách chạy:
        scrapy crawl generic_job_spider -a site_name=topcv -a keyword=ai-engineer
        scrapy crawl generic_job_spider -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1
        scrapy crawl generic_job_spider -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi,ho-chi-minh -a exp=1,2,3
        scrapy crawl generic_job_spider -a site_name=topcv -a keyword=python -a location=all -a exp=all
        scrapy crawl generic_job_spider -a site_name=itviec_python
    """
    name = "generic_job_spider"
    MAX_PLAYWRIGHT_RETRIES = 2

    def __init__(
        self, config_file=None, site_name=None, keyword=None, filters=None,
        max_pages=None, location=None, exp=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.config_file = config_file or os.getenv(
            "SITES_CONFIG_FILE",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "sites_config.json",
            ),
        )
        self.site_name_filter = site_name
        self.keyword = (keyword or "").strip().lower().replace(" ", "-")

        # Query string thô (tuỳ chọn, ghép thêm vào URL)
        self.filters = (filters or "").lstrip("?")

        self.max_pages = int(max_pages) if max_pages else int(os.getenv("MAX_PAGES", "20"))

        # location: slug hoặc id, cách nhau bởi dấu phẩy, hoặc "all"
        # exp: 1-8, cách nhau bởi dấu phẩy, hoặc "all"
        self.location_arg = (location or "").strip()
        self.exp_arg = (exp or "").strip()

        with open(self.config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.sites = data.get("sites", [])
        if self.site_name_filter:
            self.sites = [s for s in self.sites if s.get("name") == self.site_name_filter]

        if not self.sites:
            raise ValueError(
                f"Không tìm thấy site nào trong '{self.config_file}' "
                f"(site_name={self.site_name_filter!r})."
            )

        # Load map tỉnh + exp (TopCV) — thử nhiều path
        self.topcv_locations = []
        self.exp_levels = {
            "1": "Không yêu cầu",
            "2": "Dưới 1 năm",
            "3": "1 năm",
            "4": "2 năm",
            "5": "3 năm",
            "6": "4 năm",
            "7": "5 năm",
            "8": "Trên 5 năm",
        }
        candidates = [
            os.path.join(os.path.dirname(self.config_file), "topcv_locations.json"),
            os.path.join(os.getcwd(), "topcv_locations.json"),
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "topcv_locations.json",
            ),
        ]
        loc_file = next((p for p in candidates if os.path.isfile(p)), None)
        if loc_file:
            with open(loc_file, "r", encoding="utf-8") as f:
                loc_data = json.load(f)
            self.topcv_locations = loc_data.get("locations", [])
            if loc_data.get("experience_levels"):
                self.exp_levels = {
                    str(k): v for k, v in loc_data["experience_levels"].items()
                }
            self.logger.info(f"Đã load location map: {loc_file} ({len(self.topcv_locations)} tỉnh)")
        else:
            self.logger.warning(
                "Không tìm thấy topcv_locations.json — dùng fallback tối thiểu "
                "(ha-noi=1, ho-chi-minh=2). Copy file vào thư mục project để đủ 64 tỉnh."
            )
            self.topcv_locations = [
                {"id": 1, "slug": "ha-noi", "name": "Hà Nội"},
                {"id": 2, "slug": "ho-chi-minh", "name": "Hồ Chí Minh"},
                {"id": 3, "slug": "binh-duong", "name": "Bình Dương"},
                {"id": 4, "slug": "bac-ninh", "name": "Bắc Ninh"},
                {"id": 5, "slug": "dong-nai", "name": "Đồng Nai"},
                {"id": 7, "slug": "hai-phong", "name": "Hải Phòng"},
                {"id": 8, "slug": "da-nang", "name": "Đà Nẵng"},
                {"id": 9, "slug": "can-tho", "name": "Cần Thơ"},
            ]

        self.selected_locations = self._resolve_locations(self.location_arg)
        self.selected_exps = self._resolve_exps(self.exp_arg)

        self.logger.info(
            f"Sẽ crawl {len(self.sites)} site: {[s['name'] for s in self.sites]}"
            + (f" | keyword={self.keyword!r}" if self.keyword else "")
            + (f" | location={self.location_arg or 'none'}" if self.location_arg else "")
            + (f" | exp={self.exp_arg or 'none'}" if self.exp_arg else "")
            + (f" | filters={self.filters!r}" if self.filters else "")
        )
        if self.selected_locations or self.selected_exps:
            n_loc = len(self.selected_locations) or 1
            exp_s = ",".join(self.selected_exps) if self.selected_exps else "all"
            self.logger.info(
                f"TopCV filter: {n_loc} location URL(s) | exp={exp_s}"
            )

        self._seen_detail_urls = set()
        self._stats_blocks = 0
        self._stats_yielded = 0
        self._stats_skip_no_url = 0
        self._stats_skip_dupe = 0

    def _resolve_locations(self, arg: str):
        """Parse -a location=ha-noi,ho-chi-minh|1,2|ha-noi:1|all → list[dict]."""
        if not arg:
            return []
        if arg.lower() == "all":
            return list(self.topcv_locations)
        by_slug = {loc["slug"]: loc for loc in self.topcv_locations}
        by_id = {str(loc["id"]): loc for loc in self.topcv_locations}
        by_name = {loc["name"].lower(): loc for loc in self.topcv_locations}
        out = []
        for part in arg.split(","):
            part = part.strip()
            if not part:
                continue
            # Hỗ trợ "ha-noi:1" hoặc "slug:kl"
            if ":" in part:
                slug, kid = part.split(":", 1)
                slug = slug.strip().lower().replace(" ", "-")
                try:
                    kid = int(kid.strip())
                except ValueError:
                    self.logger.warning(f"location id không hợp lệ: {part!r}")
                    continue
                out.append({"id": kid, "slug": slug, "name": slug})
                continue
            key = part.lower().replace(" ", "-")
            loc = by_slug.get(key) or by_id.get(key) or by_name.get(part.lower())
            if loc:
                out.append(loc)
            else:
                self.logger.warning(
                    f"Không tìm thấy location: {part!r} — thử dạng slug:id (vd ha-noi:1)"
                )
        return out

    def _resolve_exps(self, arg: str):
        """Parse -a exp=1,2,3|all → list[str] mã exp."""
        if not arg:
            return []
        if arg.lower() == "all":
            return sorted(self.exp_levels.keys(), key=lambda x: int(x))
        out = []
        for part in arg.split(","):
            e = part.strip()
            if e in self.exp_levels:
                out.append(e)
            else:
                self.logger.warning(f"exp không hợp lệ (1-8): {part!r}")
        return out

    def _build_start_urls(self, site: dict) -> list:
        """
        Sinh danh sách start URL.
        - Không location/exp: URL keyword thường
        - Có location: ...-tai-{slug}-kl{id}
        - Có exp: ?exp=1,2,3  (gộp một query, KHÔNG tách request)
        - Nhiều location → mỗi tỉnh 1 URL (cùng chuỗi exp)
        """
        kw = self.keyword or site.get("default_keyword", "")
        keyword_path = f"-{kw}" if kw else ""

        base_template = site.get(
            "start_url_template",
            "https://www.topcv.vn/tim-viec-lam{keyword_path}",
        )
        loc_template = site.get(
            "location_exp_url_template",
            "https://www.topcv.vn/tim-viec-lam{keyword_path}-tai-{location_slug}-kl{location_id}",
        )

        locations = self.selected_locations
        exps = self.selected_exps
        # TopCV nhận exp=1,2,3 trên CÙNG một URL
        exp_query = ",".join(exps) if exps else ""

        def _append_query(url: str) -> str:
            if exp_query:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}exp={exp_query}"
            if self.filters:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{self.filters}"
            return url

        if not locations and not exp_query:
            return [_append_query(base_template.format(keyword_path=keyword_path))]

        if not locations:
            # Chỉ lọc exp, không lọc tỉnh
            return [_append_query(base_template.format(keyword_path=keyword_path))]

        urls = []
        for loc in locations:
            url = loc_template.format(
                keyword_path=keyword_path,
                location_slug=loc["slug"],
                location_id=loc["id"],
            )
            urls.append(_append_query(url))
        return urls

    # ------------------------------------------------------------------ start
    async def start(self):
        self.logger.info("start() bắt đầu chạy.")
        for site in self.sites:
            try:
                start_urls = self._build_start_urls(site)
                self.logger.info(
                    f"[{site['name']}] {len(start_urls)} start URL(s)"
                )
                needs_pw = site.get("needs_playwright_list", True)
                list_sel = site["list_item_selector"]

                for start_url in start_urls:
                    self.logger.info(f"[{site['name']}] Request tới: {start_url}")
                    meta = {
                        "playwright": needs_pw,
                        "site": site,
                        "playwright_page_goto_kwargs": {
                            "wait_until": "domcontentloaded",
                            "timeout": 45000,
                        },
                    }
                    if needs_pw:
                        meta["playwright_page_methods"] = [
                            PageMethod("wait_for_load_state", "domcontentloaded"),
                            PageMethod(
                                "wait_for_selector",
                                f"{list_sel}, div.job-item-search-result, "
                                "div[class*='job-item']",
                                state="attached",
                                timeout=45000,
                            ),
                        ]
                    yield scrapy.Request(
                        start_url,
                        meta=meta,
                        callback=self.parse_list_page,
                        errback=self.errback_close_page,
                        dont_filter=True,
                    )
            except Exception:
                self.logger.exception(
                    f"[{site.get('name')}] Lỗi khi tạo start request, bỏ qua."
                )
        self.logger.info("start() đã yield xong tất cả request.")

    # ------------------------------------------------ helpers
    @staticmethod
    def _strip_html(value: str, default="") -> str:
        """Loại bỏ mọi thẻ HTML còn sót, chuẩn hoá khoảng trắng."""
        if not value:
            return default
        # Bỏ thẻ HTML
        text = re.sub(r"<[^>]+>", " ", value)
        # Decode entity đơn giản
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&quot;", '"')
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text if text else default

    @staticmethod
    def _first_css_text(root, selector: str, default="") -> str:
        """Lấy text thuần từ CSS selector (không kèm thẻ HTML)."""
        # Ưu tiên ::text trực tiếp trên từng nhánh selector
        parts = [p.strip() for p in selector.split(",")]
        texts = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if "::text" in p or "::attr" in p:
                texts.extend(root.css(p).getall())
            else:
                texts.extend(root.css(f"{p} ::text").getall())
                # fallback: bản thân element
                texts.extend(root.css(f"{p}::text").getall())
        cleaned = " ".join(t.strip() for t in texts if t and t.strip())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned if cleaned else default

    def _split_sections_by_heading(self, full_text: str) -> dict:
        """
        Tách full text trang chi tiết thành các section theo heading cố định.
        Heading TopCV thường gặp:
          Mô tả công việc | Yêu cầu ứng viên | Quyền lợi |
          Địa điểm làm việc | Thời gian làm việc
        """
        if not full_text:
            return {}

        # Chuẩn hoá khoảng trắng
        text = re.sub(r"[ \t]+", " ", full_text)
        text = re.sub(r"\n{2,}", "\n", text)

        # CHỈ heading section thật — KHÔNG dùng từ ngắn dễ lồng trong nội dung
        # (vd "Phúc lợi" khớp nhầm "Chế độ phúc lợi vượt trội" → cắt benefit sớm)
        headings = [
            "Mô tả công việc",
            "Job Description",
            "Yêu cầu ứng viên",
            "Yêu cầu kỹ thuật",
            "Yêu cầu công việc",
            "Kỹ năng mềm",
            "Requirements",
            "Quyền lợi được hưởng",
            "Quyền lợi ứng viên",
            "Benefits",
            "Địa điểm và thời gian",
            "Địa điểm làm việc",
            "Thời gian làm việc",
            "Cách thức ứng tuyển",
        ]
        # Chỉ match heading khi đứng như tiêu đề section (đầu chuỗi / sau
        # khoảng trắng), không match giữa cụm "Chế độ phúc lợi..."
        alt = "|".join(re.escape(h) for h in headings)
        pattern = (
            r"(?:(?<=^)|(?<=\s))(?P<head>" + alt + r")(?=\s|$)"
            r"\s*(?P<body>.*?)(?="
            r"(?:(?<=\s)|^)(?:" + alt + r")(?=\s|$)|$"
            r")"
        )
        sections = {}
        for m in re.finditer(pattern, text, flags=re.I | re.S):
            key = m.group("head").strip().lower()
            body = m.group("body").strip()
            # Bỏ phần chú thích hành chính ngay đầu body địa điểm
            if "địa điểm" in key:
                body = re.sub(
                    r"^\s*\([^)]*cập nhật[^)]*\)\s*[-–:]?\s*",
                    "",
                    body,
                    flags=re.I,
                ).strip()
            if body:
                sections[key] = body
        return sections

    # Các cụm không phải location hay lẫn vào cùng selector (thời gian đăng
    # tin, trạng thái) — TopCV đôi khi dùng class tương tự cho các badge này.
    _TIME_NOISE_RE = re.compile(
        r"\d+\s*(giây|phút|giờ|ngày|tuần|tháng)\s*trước|hôm nay|hôm qua",
        re.I,
    )
    _NOISE_WORDS = ("đã xem", "nổi bật", "hết hạn", "gấp", "hot", "mới")
    _KNOWN_CITIES = [
        "Hà Nội", "Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ",
        "Bình Dương", "Đồng Nai", "Nghệ An", "Thanh Hóa", "Khánh Hòa",
        "Bắc Ninh", "Hưng Yên", "Toàn quốc",
    ]

    def _looks_like_location_noise(self, text: str) -> bool:
        """True nếu text rõ ràng KHÔNG phải location (thời gian đăng, badge...)."""
        if not text:
            return True
        if self._TIME_NOISE_RE.search(text):
            return True
        low = text.lower().strip()
        # Badge đơn lẻ kiểu "Mới", "Hot" dễ trùng — chỉ loại khi text ngắn
        # và khớp nguyên cụm (tránh loại nhầm "Hồ Chí Minh (mới)")
        if low in self._NOISE_WORDS:
            return True
        return False

    # ----------------------------------------- Classic list → detail mode
    def parse_list_page(self, response):
        site = response.meta["site"]
        page_num = response.meta.get("page_num", 1)
        self.logger.info(
            f"[{site['name']}] parse_list_page (trang {page_num}): {response.url}"
        )

        job_blocks = response.css(site["list_item_selector"])
        if not job_blocks:
            # Fallback class hay gặp trên TopCV
            for alt in (
                "div.job-item-search-result",
                "div[class*='job-item-search']",
                "div.job-list-search-result .job-item",
            ):
                job_blocks = response.css(alt)
                if job_blocks:
                    self.logger.warning(
                        f"[{site['name']}] list_item_selector rỗng → dùng fallback: {alt}"
                    )
                    break
        self.logger.info(f"[{site['name']}] Tìm thấy {len(job_blocks)} job block(s).")

        if not job_blocks:
            # Có thể dính Cloudflare — log title để nhận biết
            title = response.css("title::text").get() or ""
            self.logger.warning(
                f"[{site['name']}] Không tìm thấy job block. "
                f"title={title!r} url={response.url}"
            )
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                self.logger.error(
                    f"[{site['name']}] Có vẻ bị Cloudflare chặn. "
                    "Thử: set PLAYWRIGHT_HEADLESS=false trong .env rồi chạy lại."
                )
            return

        for job_block in job_blocks:
            item = JobListingItem()

            def _clean(sel, default=""):
                if "::text" not in sel and "::attr" not in sel:
                    parts = [p.strip() for p in sel.split(",")]
                    sel = ", ".join(
                        f"{p}::text" if p and "::" not in p else p for p in parts
                    )
                texts = job_block.css(sel).getall()
                cleaned = " ".join(t.strip() for t in texts if t and t.strip())
                return cleaned if cleaned else default

            # Title: ưu tiên text trong span tooltip / link
            title = (
                _clean("h3.title a span")
                or _clean("h3.title a")
                or _clean("h3.title")
                or _clean(site["list_title_selector"])
            )
            item["job_title"] = self._strip_html(title)
            item["company_name"] = self._strip_html(
                _clean(site["list_company_selector"])
            )
            item["salary_range"] = self._strip_html(
                _clean(site["list_salary_selector"], "N/A")
            ) or "N/A"

            # Location từ card — loại bỏ text kiểu "X ngày trước" lỡ trùng
            # class với địa điểm (đã xảy ra thực tế trên TopCV).
            loc = _clean(site["list_location_selector"])
            if self._looks_like_location_noise(loc):
                loc = ""
            if not loc:
                loc = _clean("label.address, span.address, div.address, a.city, span.city")
                if self._looks_like_location_noise(loc):
                    loc = ""
            if not loc:
                # Fallback cuối: quét toàn bộ text của card tìm tên thành phố
                # đã biết, bỏ qua hoàn toàn selector (an toàn khi DOM đổi class).
                card_text = " ".join(
                    t.strip() for t in job_block.css("::text").getall() if t.strip()
                )
                for city in self._KNOWN_CITIES:
                    if city.lower() in card_text.lower():
                        loc = city
                        break
            item["location"] = self._strip_html(loc)

            # Experience từ chip trên card (vd "1 năm", "Không yêu cầu")
            exp = ""
            for t in job_block.css("label ::text, span ::text").getall():
                t = (t or "").strip()
                low = t.lower()
                if len(t) < 40 and any(
                    k in low
                    for k in ("năm", "kinh nghiệm", "không yêu cầu", "dưới", "fresher")
                ):
                    exp = t
                    break
            item["experience"] = self._strip_html(exp)

            url_sel = site["list_url_selector"]
            if "::attr" not in url_sel:
                url_sel = f"{url_sel}::attr(href)"
            self._stats_blocks += 1
            detail_url = job_block.css(url_sel).get()

            if not detail_url:
                self._stats_skip_no_url += 1
                self.logger.warning(
                    f"[{site['name']}] Bỏ qua job không có URL: {item['job_title']}"
                )
                continue

            absolute_url = response.urljoin(detail_url)
            # Chuẩn hoá: bỏ query tracking (?ta_source=...) để so trùng đúng
            canon = absolute_url.split("?")[0].rstrip("/")
            item["job_url"] = absolute_url

            if canon in self._seen_detail_urls:
                self._stats_skip_dupe += 1
                continue
            self._seen_detail_urls.add(canon)

            needs_pw = site.get("needs_playwright_detail", True)
            meta = {
                "playwright": needs_pw,
                "item": item,
                "site": site,
                "playwright_page_goto_kwargs": {
                    "wait_until": "domcontentloaded",
                    "timeout": 30000,
                },
            }
            if needs_pw:
                meta["playwright_page_methods"] = [
                    PageMethod("wait_for_load_state", "domcontentloaded"),
                    PageMethod(
                        "wait_for_selector",
                        "h1, h2, #box-job-information-detail, "
                        "div.job-data, div.box-job-info, div.section-body",
                        state="attached",
                        timeout=10000,
                    ),
                ]

            self._stats_yielded += 1
            yield scrapy.Request(
                absolute_url,
                meta=meta,
                callback=self.parse_detail_page,
                errback=self.errback_close_page,
            )

        # --------------------------------------------------- Phân trang
        # QUAN TRỌNG: nút "Trang tiếp" của TopCV dùng data-href, KHÔNG PHẢI
        # href thường (xem devtools: <a data-href="/?page=2..." rel="next">).
        # Nếu chỉ tìm ::attr(href) sẽ luôn ra rỗng và bot chỉ dừng ở trang 1.
        next_sel = site.get("next_page_selector")
        if next_sel:
            next_url = response.css(next_sel).get()
        else:
            next_url = (
                response.css("a[rel='next']::attr(data-href)").get()
                or response.css("a[rel='next']::attr(href)").get()
                or response.css(".box-pagination a.next::attr(href)").get()
                or response.css(".pagination a.next::attr(href)").get()
            )

        if next_url and page_num < self.max_pages:
            next_url = response.urljoin(next_url)
            # data-href của TopCV có dạng "/?page=2&u_sr_id=..." — urljoin sẽ
            # thay path gốc bằng "/". Chưa xác nhận được điều này có làm mất
            # keyword search hay không (session được giữ qua u_sr_id) —
            # cảnh báo để bạn để ý log, so sánh job_title trang 2 có đúng
            # domain "ai-engineer" không.
            if site["name"] == "topcv" and "tim-viec-lam" not in next_url:
                self.logger.warning(
                    f"[{site['name']}] URL trang {page_num + 1} không còn "
                    f"path 'tim-viec-lam' ({next_url}) — kiểm tra kỹ job_title "
                    "ở trang này có đúng chủ đề tìm kiếm không, TopCV có thể "
                    "giữ ngữ cảnh search qua u_sr_id trong URL."
                )
            self.logger.info(f"[{site['name']}] → trang {page_num + 1}: {next_url}")

            needs_pw_list = site.get("needs_playwright_list", True)
            next_meta = {
                "playwright": needs_pw_list,
                "site": site,
                "page_num": page_num + 1,
                "playwright_page_goto_kwargs": {
                    "wait_until": "domcontentloaded",
                    "timeout": 45000,
                },
            }
            if needs_pw_list:
                next_meta["playwright_page_methods"] = [
                    PageMethod("wait_for_load_state", "domcontentloaded"),
                    PageMethod(
                        "wait_for_selector",
                        f"{site['list_item_selector']}, div.job-item-search-result",
                        state="attached",
                        timeout=45000,
                    ),
                ]
            yield scrapy.Request(
                next_url,
                meta=next_meta,
                callback=self.parse_list_page,
                errback=self.errback_close_page,
                dont_filter=True,
            )
        elif not next_url:
            self.logger.info(
                f"[{site['name']}] Hết trang — trang {page_num} là trang cuối."
            )
            self.logger.info(
                f"[{site['name']}] Thống kê list: blocks={self._stats_blocks} | "
                f"yield_detail={self._stats_yielded} | "
                f"skip_no_url={self._stats_skip_no_url} | "
                f"skip_dupe={self._stats_skip_dupe}"
            )
        else:
            self.logger.info(
                f"[{site['name']}] Dừng phân trang: đã đạt max_pages={self.max_pages}."
            )
            self.logger.info(
                f"[{site['name']}] Thống kê list: blocks={self._stats_blocks} | "
                f"yield_detail={self._stats_yielded} | "
                f"skip_no_url={self._stats_skip_no_url} | "
                f"skip_dupe={self._stats_skip_dupe}"
            )

    # Heading section chính — sub-heading kiểu "Chế độ phúc lợi vượt trội"
    # KHÔNG được coi là ranh giới section.
    _SECTION_HEADING_RE = re.compile(
        r"^\s*("
        r"Mô tả công việc|Job Description|"
        r"Yêu cầu ứng viên|Yêu cầu kỹ thuật|Yêu cầu công việc|Kỹ năng mềm|Requirements|"
        r"Quyền lợi được hưởng|Quyền lợi ứng viên|Benefits|"
        r"Địa điểm và thời gian|Địa điểm làm việc|Thời gian làm việc|"
        r"Cách thức ứng tuyển"
        r")\s*$",
        re.I,
    )

    def _extract_sections_via_dom(self, response, content_root_selectors):
        """Tách section bằng heading THẬT trong DOM.

        Chỉ coi h1–h4 là ranh giới KHI text khớp heading section chính
        (Mô tả công việc / Yêu cầu ứng viên / Quyền lợi ứng viên / …).
        Sub-heading bên trong (vd "2. Chế độ phúc lợi vượt trội") vẫn thuộc
        body của section đang mở — tránh cắt benefit giữa chừng.
        """
        best = {}
        best_score = -1
        for sel in content_root_selectors:
            for container in response.css(sel):
                sections = {}
                current_key = None
                current_parts = []

                def _flush():
                    if current_key and current_parts:
                        txt = " ".join(current_parts).strip()
                        if txt:
                            sections[current_key] = (
                                sections.get(current_key, "") + " " + txt
                            ).strip()

                # Duyệt mọi descendant heading + block text theo thứ tự document
                for el in container.xpath(".//*"):
                    tag = ""
                    if hasattr(el.root, "tag") and isinstance(el.root.tag, str):
                        tag = el.root.tag.lower()
                    if tag in ("h1", "h2", "h3", "h4"):
                        head_text = " ".join(
                            t.strip() for t in el.css("::text").getall() if t.strip()
                        ).strip()
                        if self._SECTION_HEADING_RE.match(head_text):
                            _flush()
                            current_key = head_text.strip().lower()
                            current_parts = []
                            continue
                        # Sub-heading → ghi vào body section hiện tại
                        if current_key is not None and head_text:
                            current_parts.append(head_text)
                    elif current_key is not None and tag in (
                        "p", "li", "div", "span", "ul", "ol", "section"
                    ):
                        # Chỉ lấy text trực tiếp của node (tránh lặp con)
                        direct = [
                            t.strip()
                            for t in el.xpath("./text()").getall()
                            if t and t.strip()
                        ]
                        if direct:
                            current_parts.append(" ".join(direct))
                _flush()

                score = sum(
                    len(v) for v in sections.values() if not self._is_noise_text(v)
                )
                if sections and score > best_score:
                    best = sections
                    best_score = score
            if best:
                break
        return best

    def parse_detail_page(self, response):
        site = response.meta["site"]
        item = response.meta["item"]
        self.logger.info(f"[{site['name']}] parse_detail_page: {response.url}")

        # --- Title từ detail nếu list trống ---
        if not item.get("job_title"):
            title = (
                response.css("h1.job-detail__info--title ::text").get()
                or response.css("h1 ::text").get()
                or response.css("h2.job-detail__info--title ::text").get()
                or response.css("div.job-detail__info--title ::text").get()
                or ""
            )
            item["job_title"] = self._strip_html(title)

        # --- Ưu tiên tách section theo heading THẬT trong DOM ---
        # (tránh bug cắt nhầm khi từ khoá heading lồng trong nội dung section
        # khác — xem docstring _extract_sections_via_dom).
        content_root_selectors = (
            "#box-job-information-detail",
            "div.job-data",
            "div.job-detail__information-detail",
            "div.box-job-info",
            "div.box-scroll",
            "div.section-body",
            "div.job-description",
            "div.job-detail",
            "div.premium-job-content",
            "div.job-content",
            "section.job-detail",
            "div#job-detail",
            "main",
        )
        section_map = self._extract_sections_via_dom(response, content_root_selectors)
        full_text = " ".join(section_map.values()) if section_map else ""

        if not section_map:
            # --- Fallback: full text làm phẳng + regex cắt theo heading ---
            # (dùng khi trang có cấu trúc lạ, vd /brand/, heading không phải
            # thẻ h1-h4 con trực tiếp của khối nội dung)
            for sel in content_root_selectors:
                parts = response.css(f"{sel} ::text").getall()
                candidate = " ".join(p.strip() for p in parts if p and p.strip())
                candidate = self._clean_detail_noise(candidate)
                if candidate and len(candidate) > len(full_text):
                    full_text = candidate

            # Brand page: DOM khác — ghép text từ mọi h2 section chính
            if "Mô tả công việc" not in full_text and "Yêu cầu ứng viên" not in full_text:
                chunks = []
                for h2 in response.css("h2"):
                    h = " ".join(t.strip() for t in h2.css("::text").getall() if t.strip())
                    if not h:
                        continue
                    low = h.lower()
                    if not any(
                        k in low
                        for k in (
                            "mô tả",
                            "yêu cầu",
                            "quyền lợi",
                            "địa điểm",
                            "thời gian",
                            "description",
                            "requirement",
                            "benefit",
                        )
                    ):
                        continue
                    # Lấy text các sibling tiếp theo cho đến h2 kế
                    following = h2.xpath(
                        "following-sibling::*[not(self::h2)][position()<=12]//text()"
                    ).getall()
                    body = " ".join(t.strip() for t in following if t and t.strip())
                    chunks.append(h + " " + body)
                if chunks:
                    full_text = self._clean_detail_noise(" ".join(chunks))

            # Fallback cuối: cắt từ body quanh các heading chính
            if "Mô tả công việc" not in (full_text or ""):
                body_txt = " ".join(
                    t.strip() for t in response.css("body ::text").getall() if t and t.strip()
                )
                m = re.search(
                    r"(Mô tả công việc\s*.+?)(Việc làm cùng công ty|Thông tin chung|Cách thức ứng tuyển|$)",
                    body_txt,
                    flags=re.I | re.S,
                )
                if m:
                    full_text = self._clean_detail_noise(m.group(1))

            section_map = self._split_sections_by_heading(full_text)

        def _pick(*keys):
            """Lấy section đầu tiên khớp key (key nằm trong tên heading)."""
            for k in keys:
                for sk, sv in section_map.items():
                    if k in sk and sv and not self._is_noise_text(sv):
                        return sv
            return ""

        def _pick_merge(*keys):
            """Gộp nhiều section liên quan (vd yêu cầu + yêu cầu kỹ thuật + kỹ năng mềm)."""
            parts = []
            seen = set()
            for k in keys:
                for sk, sv in section_map.items():
                    if k in sk and sv and not self._is_noise_text(sv) and sk not in seen:
                        seen.add(sk)
                        # Giữ nhãn heading gốc để AI đọc dễ
                        parts.append(sv if sk in k else f"{sk.title()}: {sv}")
            return "\n\n".join(parts).strip()

        desc = _pick("mô tả công việc", "job description", "responsibilities")
        # Gộp toàn bộ khối yêu cầu (ứng viên + kỹ thuật + kỹ năng mềm)
        req = _pick_merge(
            "yêu cầu ứng viên",
            "yêu cầu kỹ thuật",
            "yêu cầu công việc",
            "kỹ năng mềm",
            "requirements",
        )
        # Không dùng key ngắn "yêu cầu" trước — dễ dính nhầm
        if not req:
            req = _pick("yêu cầu ứng viên", "yêu cầu công việc", "requirements", "yêu cầu")

        benefits = _pick(
            "quyền lợi ứng viên",
            "quyền lợi được hưởng",
            "quyền lợi",
            "phúc lợi",
            "benefits",
            "đãi ngộ",
        )

        # Fallback desc: cắt đúng từ "Mô tả công việc" → trước khối yêu cầu/quyền lợi
        if not desc and full_text and len(full_text) > 80:
            m = re.search(
                r"Mô tả công việc\s*(.+?)(?="
                r"Yêu cầu ứng viên|Yêu cầu kỹ thuật|Yêu cầu công việc|"
                r"Requirements|Quyền lợi ứng viên|Quyền lợi được hưởng|"
                r"Quyền lợi|Benefits|Địa điểm|$)",
                full_text,
                flags=re.I | re.S,
            )
            if m:
                candidate = m.group(1).strip()
                if candidate and not self._is_noise_text(candidate):
                    desc = candidate[:4000]
            elif not self._is_noise_text(full_text):
                desc = full_text[:4000]

        # Fallback benefits nếu vẫn trống
        if not benefits and full_text:
            m = re.search(
                r"(?:Quyền lợi ứng viên|Quyền lợi được hưởng|Quyền lợi)\s*(.+?)(?="
                r"Địa điểm|Thời gian làm việc|Cách thức ứng tuyển|$)",
                full_text,
                flags=re.I | re.S,
            )
            if m:
                candidate = m.group(1).strip()
                if candidate and not self._is_noise_text(candidate):
                    benefits = candidate[:3000]

        # Fallback requirements
        if not req and full_text:
            m = re.search(
                r"(?:Yêu cầu ứng viên|Yêu cầu)\s*(.+?)(?="
                r"Quyền lợi ứng viên|Quyền lợi được hưởng|Quyền lợi|Benefits|"
                r"Địa điểm|Thời gian làm việc|$)",
                full_text,
                flags=re.I | re.S,
            )
            if m:
                candidate = m.group(1).strip()
                if candidate and not self._is_noise_text(candidate):
                    req = candidate[:4000]

        if self._is_noise_text(desc):
            desc = ""
        if self._is_noise_text(req):
            req = ""
        if self._is_noise_text(benefits):
            benefits = ""

        item["job_description"] = self._strip_html(desc)

        item["job_requirements"] = self._strip_html(req)
        item["job_benefits"] = self._strip_html(benefits)

        # Location
        if not item.get("location"):
            loc = section_map.get("địa điểm làm việc", "")
            if not loc:
                loc = " ".join(
                    response.css(
                        "div.box-address ::text, a.address ::text, "
                        "div.job-detail__info--main-content a[href*='dia-diem'] ::text, "
                        "div.job-detail__info--main-content a[href*='tai-'] ::text"
                    ).getall()
                )
            loc = self._clean_detail_noise(loc)
            loc = re.sub(
                r"Địa điểm làm việc\s*\([^)]*\)\s*[-–:]?\s*", "", loc, flags=re.I
            )
            item["location"] = self._strip_html(loc)[:150]

        # Experience chips
        if not item.get("experience"):
            for t in response.css("div.job-detail__info--main-content ::text").getall():
                t = t.strip()
                low = t.lower()
                if any(k in low for k in ("năm", "kinh nghiệm", "không yêu cầu", "dưới")):
                    if len(t) < 40:
                        item["experience"] = self._strip_html(t)
                        break

        self.logger.info(
            f"[{site['name']}] detail OK: {item.get('job_title')!r} "
            f"| loc={item.get('location')!r} "
            f"| desc={len(item.get('job_description') or '')} "
            f"| req={len(item.get('job_requirements') or '')} "
            f"| ben={len(item.get('job_benefits') or '')}"
        )
        yield item

    @staticmethod
    def _clean_detail_noise(text: str) -> str:
        """Loại JS, 'Việc làm liên quan', 'Đang tải...' khỏi text detail."""
        if not text:
            return ""
        text = re.split(
            r"Việc làm liên quan|Similar jobs|Việc làm cùng công ty|"
            r"Việc làm cùng|Có thể bạn quan tâm",
            text,
            maxsplit=1,
            flags=re.I,
        )[0]
        text = re.sub(r"const\s+\w+\s*=\s*\[[\s\S]*", " ", text)
        text = re.sub(r"function\s*\([^)]*\)\s*\{[\s\S]*", " ", text)
        text = re.sub(r"\{[\"']company[\"']\s*:", " ", text)
        text = re.sub(r"Đang tải[^.]*\.?", " ", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _is_noise_text(text: str) -> bool:
        """True nếu text chỉ là nhiễu (related jobs / loading / JS)."""
        if not text or len(text) < 40:
            return True
        low = text.lower().strip()
        if low.startswith("việc làm liên quan"):
            return True
        if "đang tải việc làm" in low:
            return True
        if "similarjobs" in low.replace(" ", ""):
            return True
        if low.startswith("const ") or low.startswith("{"):
            return True
        # Chủ yếu là cụm 'việc làm liên quan' lặp lại
        if low.count("việc làm liên quan") >= 1 and len(low) < 200:
            return True
        return False

    # ----------------------------------------- errback
    async def errback_close_page(self, failure):
        request = failure.request
        self.logger.error(f"Request thất bại: {request.url} — {repr(failure.value)}")

        page = request.meta.get("playwright_page")
        if page and not getattr(page, "is_closed", lambda: True)():
            try:
                await page.close()
            except Exception:
                pass

        retry_count = request.meta.get("playwright_retry_count", 0)
        err_repr = repr(failure.value)
        is_crash = any(
            s in err_repr
            for s in (
                "TargetClosedError",
                "Target closed",
                "Browser closed",
                "context has been closed",
            )
        )

        if is_crash and retry_count < self.MAX_PLAYWRIGHT_RETRIES:
            retry_count += 1
            self.logger.warning(
                f"Crash — thử lại {retry_count}/{self.MAX_PLAYWRIGHT_RETRIES}: {request.url}"
            )
            new_meta = dict(request.meta)
            new_meta["playwright_retry_count"] = retry_count
            new_meta.pop("playwright_page", None)
            yield request.replace(meta=new_meta, dont_filter=True)
        else:
            self.logger.error(f"Bỏ qua request: {request.url}")