from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from DrissionPage import ChromiumOptions, ChromiumPage

from utils.runtime import runtime

logger = logging.getLogger(__name__)

PRODUCT_URL_PATTERNS = [
    re.compile(r"/product/(\d+)/(\d+)") ,
    re.compile(r"-i\.(\d+)\.(\d+)") ,
    re.compile(r"/i\.(\d+)\.(\d+)") ,
]


class ProductShopFinder:
    def __init__(self, keywords: list[str], max_pages: int = 1, max_shops: int = 100):
        self.keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
        self.max_pages = max_pages
        self.max_shops = max_shops
        self.project_root = runtime.paths.project_root
        self.output_file = runtime.paths.shops_file
        self.shop_detail_file = runtime.paths.shop_detail_file

    def _normalize_id(self, value):
        if value is None:
            return ""
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        return text

    def _load_existing_shop_ids(self) -> set[str]:
        existing = set()
        if self.shop_detail_file.exists():
            try:
                df = pd.read_csv(self.shop_detail_file)
                if 'shopid' in df.columns:
                    existing.update(
                        self._normalize_id(value)
                        for value in df['shopid'].dropna().tolist()
                        if self._normalize_id(value)
                    )
            except Exception as error:
                logger.warning("Không đọc được %s: %s", self.shop_detail_file, error)
        if self.output_file.exists():
            try:
                with self.output_file.open('r', encoding='utf-8') as file:
                    existing.update(
                        self._normalize_id(line)
                        for line in file
                        if self._normalize_id(line)
                    )
            except Exception as error:
                logger.warning("Không đọc được %s: %s", self.output_file, error)
        return existing

    def _extract_from_href(self, href: str | None) -> tuple[str, str] | None:
        if not href:
            return None
        for pattern in PRODUCT_URL_PATTERNS:
            match = pattern.search(href)
            if match:
                return match.group(1), match.group(2)
        return None

    def _append_to_output(self, new_shop_ids: set[str]):
        existing_lines = set()
        if self.output_file.exists():
            with self.output_file.open('r', encoding='utf-8') as file:
                existing_lines = {self._normalize_id(line) for line in file if self._normalize_id(line)}

        merged = existing_lines.union(new_shop_ids)
        with self.output_file.open('w', encoding='utf-8') as file:
            for value in sorted(merged):
                file.write(f"{value}\n")

    def __call__(self):
        if not self.keywords:
            logger.warning("Không có keyword để tìm shop từ sản phẩm.")
            return []

        co = ChromiumOptions()
        if runtime.chrome_path:
            co.set_browser_path(runtime.chrome_path)

        co.set_local_port(runtime.shop_finder_port)
        co.set_user_data_path(str(runtime.paths.profile_dir))

        logger.info("🚀 Khởi động công cụ TÌM SHOP TỪ SẢN PHẨM...")

        existing_shop_ids = self._load_existing_shop_ids()
        found_shop_ids: list[str] = []
        found_shop_id_set: set[str] = set()

        try:
            page = ChromiumPage(co)
            page.set.window.max()
            page.get("https://shopee.vn/")
            time.sleep(5)

            for keyword in self.keywords:
                if len(found_shop_ids) >= self.max_shops:
                    break

                logger.info("\n🔍 Đang quét sản phẩm theo keyword: '%s'", keyword)
                for page_index in range(self.max_pages):
                    if len(found_shop_ids) >= self.max_shops:
                        break

                    url = f"https://shopee.vn/search?keyword={quote_plus(keyword)}&page={page_index}"
                    logger.info("   📄 Mở trang %s: %s", page_index + 1, url)
                    page.get(url)

                    for _ in range(4):
                        page.scroll.down(800)
                        time.sleep(1)

                    anchors = []
                    try:
                        anchors = page.eles('a[href*="/product/"], a[href*="-i."], a[href*="/i."]')
                    except Exception as error:
                        logger.warning("   ⚠️ Không đọc được anchors trên trang search: %s", error)

                    added_this_page = 0
                    for anchor in anchors:
                        href = None
                        try:
                            href = anchor.attr('href')
                        except Exception:
                            try:
                                href = anchor.link
                            except Exception:
                                href = None

                        ids = self._extract_from_href(href)
                        if not ids:
                            continue

                        shop_id, item_id = ids
                        if not shop_id or not item_id:
                            continue
                        if shop_id in existing_shop_ids or shop_id in found_shop_id_set:
                            continue

                        found_shop_id_set.add(shop_id)
                        found_shop_ids.append(shop_id)
                        added_this_page += 1
                        logger.info("      ✅ Shop mới: %s (từ item %s)", shop_id, item_id)

                        if len(found_shop_ids) >= self.max_shops:
                            break

                    logger.info("   -> Trang %s thêm mới %s shop, tổng hiện có %s/%s", page_index + 1, added_this_page, len(found_shop_ids), self.max_shops)
                    time.sleep(2)

        except Exception as error:
            logger.error("Lỗi trình duyệt ProductShopFinder: %s", error)
        finally:
            try:
                if 'page' in locals():
                    page.quit()
            except Exception:
                pass

        if found_shop_ids:
            self._append_to_output(set(found_shop_ids))
            logger.info("\n💾 Đã lưu %s shop mới vào %s", len(found_shop_ids), self.output_file)
        else:
            logger.warning("\n❌ Không tìm thêm được shop nào mới từ sản phẩm!")

        return found_shop_ids
