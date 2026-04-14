from utils.utils import timer

import os
import logging
import asyncio
import datetime
import aiohttp
import pandas as pd
import random
from pydantic import BaseModel, ConfigDict
from crawlers.csv_store import upsert_csv
from utils.runtime import runtime

logger = logging.getLogger(__name__)


class ShopParams(BaseModel):
    shop_created: str | None = ""
    insert_date: str | None = ""
    shopid: int | None = 0
    name: str | None = ""
    follower_count: int | None = 0
    has_decoration: bool | None = False
    item_count: int | None = 0
    response_rate: int | None = 0
    response_time: int | None = 0
    rating_star: float | None = 0.0
    shop_rating_normal: int | None = 0
    shop_rating_bad: int | None = 0
    shop_rating_good: int | None = 0
    is_official_shop: bool | None = False
    is_preferred_plus_seller: bool | None = False
    ctime: int | None = 0
    cancellation_rate: float | int | None = 0
    cancellation_visibility: int | None = 0
    cancellation_warning: int | None = 0

    model_config = ConfigDict(extra="ignore")


class ShopDetailCrawler:
    def __init__(self):
        self.shop_detail_api = "https://shopee.vn/api/v4/shop/get_shop_detail?"
        self.shop_detail = []
        self.output_file = runtime.paths.shop_detail_file

    def _normalize_identifier(self, value):
        if value is None:
            return ""
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        return text

    def _build_query_urls(self, identifier):
        normalized = self._normalize_identifier(identifier)
        if not normalized:
            return []

        candidates = [f"username={normalized}"]
        if normalized.isdigit():
            candidates = [
                f"shopid={normalized}",
                f"shop_id={normalized}",
                f"username={normalized}",
            ]

        return [self.shop_detail_api + candidate for candidate in candidates]

    def _load_existing_shop_ids(self):
        if not self.output_file.exists():
            return set()

        try:
            existing = pd.read_csv(self.output_file)
        except Exception:
            return set()

        if 'shopid' not in existing.columns:
            return set()

        return {
            self._normalize_identifier(value)
            for value in existing['shopid'].dropna().tolist()
            if self._normalize_identifier(value)
        }

    @timer
    def __call__(self, input_shop_names):
        self.shop_detail = []
        existing_shop_ids = self._load_existing_shop_ids()

        normalized_inputs = []
        seen_inputs = set()
        for raw_identifier in input_shop_names:
            normalized = self._normalize_identifier(raw_identifier)
            if not normalized or normalized in seen_inputs:
                continue
            seen_inputs.add(normalized)
            normalized_inputs.append(normalized)

        async def get_shop_detail(client, query_url):
            try:
                async with client.get(query_url) as response:
                    if response.status != 200:
                        logger.error(f" Bị chặn hoặc lỗi ở link: {query_url} (Status: {response.status})")
                        return

                    res = await response.json()
                    data = res.get("data")
                    if not data:
                        logger.warning(f" Không có dữ liệu trả về cho shop này: {query_url}")
                        return

                    follower_count = data.get("follower_count", 0)
                    has_decoration = data.get("has_decoration", False)
                    item_count = data.get("item_count", 0)
                    response_rate = data.get("response_rate", 0)
                    response_time = data.get("response_time", 0)
                    rating_star = data.get("rating_star", 0.0)
                    shop_rating = data.get("shop_rating", {})
                    is_official_shop = data.get("is_official_shop", False)
                    is_preferred_plus_seller = data.get("is_preferred_plus_seller", False)
                    ctime = data.get("ctime", 0)
                    seller_metrics = data.get("seller_metrics", {})

                    shop_created = datetime.datetime.fromtimestamp(ctime).strftime('%Y-%m-%d %H:%M:%S') if ctime else ""
                    insert_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    shop_info = ShopParams(
                        shop_created=shop_created,
                        insert_date=insert_date,
                        shopid=data.get("shopid", 0),
                        name=data.get("name", ""),
                        follower_count=follower_count,
                        has_decoration=has_decoration,
                        item_count=item_count,
                        response_rate=response_rate,
                        response_time=response_time,
                        rating_star=rating_star,
                        shop_rating_normal=shop_rating.get("normal", 0),
                        shop_rating_bad=shop_rating.get("bad", 0),
                        shop_rating_good=shop_rating.get("good", 0),
                        is_official_shop=is_official_shop,
                        is_preferred_plus_seller=is_preferred_plus_seller,
                        ctime=ctime,
                        cancellation_rate=seller_metrics.get("cancellation_rate", 0),
                        cancellation_visibility=seller_metrics.get("cancellation_visibility", 0),
                        cancellation_warning=seller_metrics.get("cancellation_warning", 0)
                    )
                    self.shop_detail.append(shop_info.model_dump())
                    logger.info(f"   ✅ Đã lấy thông tin Shop: {data.get('name', '')} (ID: {data.get('shopid', 0)})")

            except Exception as e:
                logger.error(f"Error parse: {query_url} Error {e}")

        async def main(crawler_shop_urls):
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "referer": "https://shopee.vn/",
                "X-Requested-With": "XMLHttpRequest",
            }

            # --- CHÌA KHÓA NẰM Ở ĐÂY ---
            # Chỉ cho phép tối đa 3 requests chạy song song
            sem = asyncio.Semaphore(3)

            async def safe_fetch(client, url):
                async with sem:
                    # Ngủ ngẫu nhiên 1 đến 2.5 giây để tránh bị đánh dấu spam
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    await get_shop_detail(client, url)

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False, limit=100),
                                             headers=headers) as client:
                tasks = [safe_fetch(client, url) for url in crawler_shop_urls]
                await asyncio.gather(*tasks)

        urls = []
        skipped_existing = 0
        for identifier in normalized_inputs:
            if identifier.isdigit() and identifier in existing_shop_ids:
                skipped_existing += 1
                logger.info("   ⏭️ Bỏ qua shop đã có trong shop_detail.csv: %s", identifier)
                continue
            urls.extend(self._build_query_urls(identifier))

        # Khắc phục lỗi event loop trên môi trường Windows
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        if urls:
            asyncio.run(main(urls))
        else:
            logger.info("Không còn shop mới để crawl sau khi lọc trùng.")

        columns = list(ShopParams.model_fields.keys())
        df = pd.DataFrame(self.shop_detail, columns=columns)
        if not df.empty:
            df = upsert_csv(
                self.output_file,
                df,
                columns=columns,
                key_columns=["shopid"],
            )
            logger.info("Saved %s unique shop details to %s.", len(df), self.output_file)
        elif skipped_existing > 0:
            logger.info("Đã bỏ qua %s shop vì đã có trong shop_detail.csv.", skipped_existing)
        return df
