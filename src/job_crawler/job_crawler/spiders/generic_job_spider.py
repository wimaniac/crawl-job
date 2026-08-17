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
        scrapy crawl generic_job_spider -a site_name=topcv
        scrapy crawl generic_job_spider -a site_name=topcv -a keyword=ai-engineer
        scrapy crawl generic_job_spider -a site_name=itviec_python
    """
    name = "generic_job_spider"
    MAX_PLAYWRIGHT_RETRIES = 2

    def __init__(self, config_file=None, site_name=None, keyword=None, *args, **kwargs):
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

        self.logger.info(
            f"Sẽ crawl {len(self.sites)} site: {[s['name'] for s in self.sites]}"
            + (f" | keyword={self.keyword!r}" if self.keyword else "")
        )

    def _build_start_url(self, site: dict) -> str:
        if "start_url_template" in site:
            kw = self.keyword or site.get("default_keyword", "")
            keyword_path = f"-{kw}" if kw else ""
            return site["start_url_template"].format(keyword_path=keyword_path)
        return site["start_url"]

    # ------------------------------------------------------------------ start
    async def start(self):
        self.logger.info("start() bắt đầu chạy.")
        for site in self.sites:
            try:
                start_url = self._build_start_url(site)
                self.logger.info(f"[{site['name']}] Request tới: {start_url}")

                needs_pw = site.get("needs_playwright_list", True)
                use_panel = site.get("use_side_panel", False)

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
                        PageMethod(
                            "wait_for_selector",
                            site["list_item_selector"],
                            state="visible",
                            timeout=25000,
                        ),
                    ]

                # Side-panel mode cần giữ page object để click từng job
                if use_panel:
                    meta["playwright_include_page"] = True
                    callback = self.parse_list_with_panel
                else:
                    callback = self.parse_list_page

                yield scrapy.Request(
                    start_url,
                    meta=meta,
                    callback=callback,
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
    def _text(node_or_list, default="") -> str:
        """Lấy text sạch từ Selector / list string."""
        if node_or_list is None:
            return default
        if isinstance(node_or_list, str):
            return node_or_list.strip() or default
        # SelectorList
        parts = node_or_list.css("::text").getall() if hasattr(node_or_list, "css") else []
        if not parts and hasattr(node_or_list, "getall"):
            parts = node_or_list.getall()
        cleaned = " ".join(p.strip() for p in parts if p and p.strip())
        return cleaned if cleaned else default

    @staticmethod
    def _first_css_text(root, selector: str, default="") -> str:
        texts = root.css(f"{selector} ::text").getall()
        cleaned = " ".join(t.strip() for t in texts if t and t.strip())
        return cleaned if cleaned else default

    def _compose_raw(self, item: JobListingItem) -> str:
        """Ghép các phần mô tả thành job_description_raw cho AI pipeline."""
        parts = []
        mapping = [
            ("Mô tả công việc", item.get("job_description")),
            ("Yêu cầu ứng viên", item.get("job_requirements")),
            ("Tech stack", item.get("tech_stack")),
            ("Quyền lợi", item.get("job_benefits")),
        ]
        for label, val in mapping:
            if val:
                parts.append(f"### {label}\n{val}")
        return "\n\n".join(parts)

    # ----------------------------------------- TopCV side-panel mode
    async def parse_list_with_panel(self, response):
        """
        TopCV: click từng job card → đọc side panel (tránh /brand/... URL).
        Cần meta playwright_include_page=True.
        """
        site = response.meta["site"]
        page = response.meta.get("playwright_page")
        self.logger.info(f"[{site['name']}] parse_list_with_panel: {response.url}")

        if page is None:
            self.logger.error(
                f"[{site['name']}] Không có playwright_page — "
                "kiểm tra playwright_include_page=True."
            )
            return

        try:
            cards = await page.query_selector_all(site["list_item_selector"])
            self.logger.info(f"[{site['name']}] Tìm thấy {len(cards)} job card(s).")

            if not cards:
                self.logger.warning(f"[{site['name']}] Không có job card nào.")
                return

            for idx, card in enumerate(cards):
                try:
                    item = await self._extract_from_panel(page, card, site, response, idx)
                    if item:
                        yield item
                except Exception as e:
                    self.logger.error(
                        f"[{site['name']}] Lỗi khi xử lý job card #{idx}: {e}"
                    )
        finally:
            # Đóng page thủ công vì playwright_include_page=True
            try:
                await page.close()
            except Exception:
                pass

    async def _extract_from_panel(self, page, card, site, response, idx):
        """Click 1 card → đọc panel → trả về JobListingItem."""
        # --- thông tin cơ bản từ card (trước khi click) ---
        card_html = await card.inner_html()
        # Dùng scrapy Selector trên HTML của card
        from scrapy.selector import Selector
        card_sel = Selector(text=f"<div>{card_html}</div>")

        company = self._first_css_text(
            card_sel, site.get("list_company_selector", "a.company, span.company-name")
        )
        salary = self._first_css_text(
            card_sel, site.get("list_salary_selector", "label.title-salary")
        ) or "N/A"
        list_location = self._first_css_text(
            card_sel, site.get("list_location_selector", "a.address")
        )
        # URL dự phòng từ thẻ a
        href = card_sel.css("h3.title a::attr(href)").get()
        fallback_url = response.urljoin(href) if href else response.url

        # --- click mở panel ---
        click_sel = site.get("list_click_selector", "div.body")
        click_target = await card.query_selector(click_sel)
        if click_target is None:
            click_target = card

        panel_root = site.get("panel_root", "div.job-list-detail")
        old_title = ""
        try:
            old_el = await page.query_selector(f"{panel_root} h2")
            if old_el:
                old_title = (await old_el.inner_text() or "").strip()
        except Exception:
            pass

        await click_target.click()

        # Đợi panel cập nhật (title đổi hoặc xuất hiện)
        try:
            await page.wait_for_selector(panel_root, state="visible", timeout=10000)
            # Đợi title đổi (tránh đọc panel cũ)
            if old_title:
                await page.wait_for_function(
                    """(old) => {
                        const el = document.querySelector('div.job-list-detail h2');
                        return el && el.innerText.trim() !== old;
                    }""",
                    arg=old_title,
                    timeout=8000,
                )
            else:
                await page.wait_for_timeout(800)
        except Exception as e:
            self.logger.warning(
                f"[{site['name']}] Panel chưa sẵn sàng cho card #{idx}: {e}"
            )

        # --- đọc panel ---
        panel = await page.query_selector(panel_root)
        if panel is None:
            self.logger.warning(f"[{site['name']}] Không tìm thấy panel cho card #{idx}")
            return None

        panel_html = await panel.inner_html()
        panel_sel = Selector(text=f"<div>{panel_html}</div>")

        title = self._first_css_text(
            panel_sel, site.get("panel_title", "div.box-title h2, h2")
        )
        if not title:
            title = self._first_css_text(card_sel, "h3.title a, h3.title")

        # Header chips: Thỏa thuận | Hà Nội | Trên 5 năm
        header_texts = [
            t.strip()
            for t in panel_sel.css("div.box-info-header ::text, div.header-normal-default ::text").getall()
            if t and t.strip()
        ]
        # Lọc text có ý nghĩa
        experience = ""
        location = list_location
        for t in header_texts:
            low = t.lower()
            if any(k in low for k in ("năm", "kinh nghiệm", "không yêu cầu", "dưới")):
                experience = t
            elif any(k in low for k in ("hà nội", "hồ chí minh", "đà nẵng", "cần thơ",
                                         "hải phòng", "remote", "toàn quốc")) or (
                len(t) < 30 and "thỏa thuận" not in low and "triệu" not in low
            ):
                if not location:
                    location = t

        # Location từ box-address
        addr = self._first_css_text(panel_sel, "div.box-address")
        if addr:
            # Bỏ "và X nơi khác"
            addr = re.sub(r"\s*và\s+\d+\s+nơi khác", "", addr, flags=re.I).strip()
            location = addr or location

        # Parse các section theo heading h3
        sections = self._parse_panel_sections(panel_sel)

        job_description = sections.get("mô tả công việc", "") or sections.get("mô tả", "")
        job_requirements = (
            sections.get("yêu cầu ứng viên", "")
            or sections.get("yêu cầu", "")
            or sections.get("requirements", "")
        )
        tech_stack = (
            sections.get("tech stack", "")
            or sections.get("tech stack you'll work in", "")
            or sections.get("công nghệ", "")
        )
        job_benefits = sections.get("quyền lợi", "") or sections.get("benefits", "")

        # URL chi tiết (nút "Xem chi tiết")
        detail_href = panel_sel.css(
            "a[href*='/viec-lam/']::attr(href), a:contains('Xem chi tiết')::attr(href)"
        ).get()
        job_url = response.urljoin(detail_href) if detail_href else fallback_url

        # Tránh URL /brand/ nếu có thể
        if "/brand/" in (job_url or "") and href and "/viec-lam/" in href:
            job_url = response.urljoin(href)

        item = JobListingItem()
        item["job_title"] = title
        item["company_name"] = company
        item["location"] = location
        item["salary_range"] = salary
        item["experience"] = experience
        item["job_url"] = job_url or fallback_url
        item["job_description"] = job_description
        item["job_requirements"] = job_requirements
        item["tech_stack"] = tech_stack
        item["job_benefits"] = job_benefits
        item["job_description_raw"] = self._compose_raw(item)

        self.logger.info(
            f"[{site['name']}] #{idx} {title!r} | {company!r} | {location!r}"
        )
        return item

    def _parse_panel_sections(self, panel_sel) -> dict:
        """
        Tách nội dung panel theo các heading h3.
        Trả về dict: { 'mô tả công việc': '...', 'yêu cầu ứng viên': '...', ... }
        """
        sections = {}
        # Mỗi block thường là: h3 + div.content-tab / ul / sibling
        headings = panel_sel.css("div.box-job-info h3, div.box-scroll h3")
        for h3 in headings:
            heading_text = " ".join(
                t.strip() for t in h3.css("::text").getall() if t.strip()
            ).strip().lower()
            if not heading_text:
                continue

            # Lấy sibling content ngay sau h3
            # Scrapy không có next_sibling dễ dùng → lấy parent rồi text sau heading
            parent = h3.xpath("..")
            # Lấy tất cả text trong parent, bỏ heading
            all_text = " ".join(
                t.strip() for t in parent.css("::text").getall() if t and t.strip()
            )
            # Cắt phần heading ra
            content = all_text
            for variant in (heading_text, heading_text.title(), heading_text.upper()):
                if content.lower().startswith(variant.lower()):
                    content = content[len(variant):].strip()
                    break
            # Một số heading bị lặp
            content = re.sub(
                r"^" + re.escape(heading_text), "", content, flags=re.I
            ).strip()

            if content:
                sections[heading_text] = content

        return sections

    # ----------------------------------------- Classic list → detail mode
    def parse_list_page(self, response):
        site = response.meta["site"]
        self.logger.info(f"[{site['name']}] parse_list_page: {response.url}")

        job_blocks = response.css(site["list_item_selector"])
        self.logger.info(f"[{site['name']}] Tìm thấy {len(job_blocks)} job block(s).")

        if not job_blocks:
            self.logger.warning(f"[{site['name']}] Không tìm thấy job block.")
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

            item["job_title"] = _clean(site["list_title_selector"])
            item["company_name"] = _clean(site["list_company_selector"])
            item["location"] = _clean(site["list_location_selector"])
            item["salary_range"] = _clean(site["list_salary_selector"], "N/A")

            url_sel = site["list_url_selector"]
            if "::attr" not in url_sel:
                url_sel = f"{url_sel}::attr(href)"
            detail_url = job_block.css(url_sel).get()

            if not detail_url:
                self.logger.warning(
                    f"[{site['name']}] Bỏ qua job không có URL: {item['job_title']}"
                )
                continue

            absolute_url = response.urljoin(detail_url)
            item["job_url"] = absolute_url

            needs_pw = site.get("needs_playwright_detail", True)
            meta = {
                "playwright": needs_pw,
                "item": item,
                "site": site,
                "playwright_page_goto_kwargs": {
                    "wait_until": "domcontentloaded",
                    "timeout": 45000,
                },
            }
            if needs_pw:
                meta["playwright_page_methods"] = [
                    PageMethod("wait_for_load_state", "domcontentloaded"),
                ]

            yield scrapy.Request(
                absolute_url,
                meta=meta,
                callback=self.parse_detail_page,
                errback=self.errback_close_page,
            )

    def parse_detail_page(self, response):
        site = response.meta["site"]
        item = response.meta["item"]
        self.logger.info(f"[{site['name']}] parse_detail_page: {response.url}")

        desc_sel = site.get("detail_description_selector", "div.job-description")
        parts = response.css(f"{desc_sel} ::text").getall()
        description = " ".join(p.strip() for p in parts if p and p.strip()).strip()

        item["job_description"] = description
        item["job_description_raw"] = description
        yield item

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