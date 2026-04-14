import datetime
import hashlib
import json
import logging
import random
import time

import pandas as pd
from DrissionPage import ChromiumOptions, ChromiumPage

from crawlers.csv_store import load_csv, save_csv, upsert_dataframe
from utils.runtime import runtime

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

STAR_BUCKETS = [1, 2, 3, 4, 5]
MAX_DOM_PAGES_PER_STAR = 3
SLEEP_PAGES = (1.5, 2.5)
SLEEP_STARS = (1, 2)
SLEEP_ITEMS = (3, 6)
LISTEN_PATH = 'api/v2/item/get_ratings'
REVIEW_COLUMNS = [
    'code',
    'itemid',
    'shopid',
    'rating_star',
    'sample_index',
    'rating_id',
    'author_username',
    'like_count',
    'ctime',
    't_ctime',
    'comment',
    'product_items',
    'insert_date',
]


class ReviewCrawler:
    def __init__(self):
        self.project_root = str(runtime.paths.project_root)
        self.data_dir = str(runtime.paths.data_dir)
        self.today_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.page = None
        self.items_done = 0
        self.reviews_per_star_sample = runtime.reviews_per_star_sample
        self.refresh_every = runtime.review_refresh_every
        self.pdp_path = runtime.paths.product_detail_file
        self.reviews_path = runtime.paths.review_samples_file

    def _empty_star_counts(self):
        return {star: 0 for star in STAR_BUCKETS}

    def _normalize_id(self, value):
        if pd.isna(value):
            return ""
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        return text

    def _product_key(self, itemid, shopid):
        item_key = self._normalize_id(itemid)
        shop_key = self._normalize_id(shopid)
        if not item_key or not shop_key:
            return ""
        return f"{shop_key}:{item_key}"

    def _product_code(self, itemid, shopid):
        item_key = self._normalize_id(itemid)
        shop_key = self._normalize_id(shopid)
        if not item_key or not shop_key:
            return ""
        return f"{shop_key}_{item_key}"

    def _target_samples_for_star(self, star_counts, star):
        available = int(star_counts.get(star, 0) or 0)
        return max(0, min(available, self.reviews_per_star_sample))

    def _ensure_product_columns(self, df_products):
        frame = df_products.copy()
        for star in STAR_BUCKETS:
            star_column = f'star_{star}'
            sampled_column = f'review_sampled_star_{star}'
            if star_column not in frame.columns:
                frame[star_column] = -1
            if sampled_column not in frame.columns:
                frame[sampled_column] = 0

        if 'review_samples_done' not in frame.columns:
            frame['review_samples_done'] = 0

        return frame

    def _normalize_rating_id(self, review, itemid, shopid, star):
        raw_rating_id = review.get("rating_id")
        if raw_rating_id is not None:
            rating_text = self._normalize_id(raw_rating_id)
            if rating_text:
                return rating_text

        fallback = "|".join([
            self._normalize_id(shopid),
            self._normalize_id(itemid),
            str(star),
            str(review.get("author_username", "")),
            str(review.get("ctime", 0) or 0),
            (review.get("comment") or "").strip(),
        ])
        return f"synthetic-{hashlib.md5(fallback.encode('utf-8')).hexdigest()}"

    def _reindex_review_samples(self, reviews_df):
        frame = load_csv(self.reviews_path, REVIEW_COLUMNS) if reviews_df is None else reviews_df.copy()
        if frame.empty:
            return pd.DataFrame(columns=REVIEW_COLUMNS)

        frame = frame.copy()
        if 'code' not in frame.columns:
            frame['code'] = ''
        frame["shopid"] = frame["shopid"].apply(self._normalize_id)
        frame["itemid"] = frame["itemid"].apply(self._normalize_id)
        frame["rating_id"] = frame["rating_id"].apply(self._normalize_id)
        frame["code"] = frame["code"].apply(self._normalize_id)
        missing_code_mask = frame["code"].eq("")
        if missing_code_mask.any():
            frame.loc[missing_code_mask, "code"] = frame.loc[missing_code_mask].apply(
                lambda row: self._product_code(row["itemid"], row["shopid"]),
                axis=1,
            )
        frame = frame.drop_duplicates(
            subset=["code", "rating_id", "rating_star"],
            keep="last",
        ).reset_index(drop=True)
        frame["_code_key"] = frame["code"].apply(self._normalize_id)
        frame["_rating_star"] = pd.to_numeric(frame["rating_star"], errors="coerce").fillna(0).astype(int)
        frame["_sample_index"] = pd.to_numeric(frame["sample_index"], errors="coerce").fillna(0).astype(int)
        frame["_ctime"] = pd.to_numeric(frame["ctime"], errors="coerce").fillna(0)
        frame["_rating_id"] = frame["rating_id"].fillna("").astype(str)

        frame = frame.sort_values(
            by=["_code_key", "_rating_star", "_sample_index", "_ctime", "_rating_id"],
            ascending=[True, True, True, False, True],
        ).reset_index(drop=True)

        frame["sample_index"] = (
            frame.groupby(["_code_key", "_rating_star"]).cumcount() + 1
        )
        frame = frame[frame["sample_index"] <= self.reviews_per_star_sample]
        frame = frame.drop(columns=["_code_key", "_rating_star", "_sample_index", "_ctime", "_rating_id"])
        return frame[REVIEW_COLUMNS].reset_index(drop=True)

    def _load_existing_reviews(self):
        canonical_df = load_csv(self.reviews_path, REVIEW_COLUMNS)
        reviews_df = self._reindex_review_samples(canonical_df)
        save_csv(self.reviews_path, reviews_df, REVIEW_COLUMNS)
        return reviews_df

    def _build_review_cache(self, reviews_df):
        count_map = {}
        rating_ids_map = {}

        for row in reviews_df.itertuples(index=False):
            product_key = self._product_key(getattr(row, "itemid", None), getattr(row, "shopid", None))
            if not product_key:
                continue

            rating_star = pd.to_numeric(getattr(row, "rating_star", None), errors="coerce")
            if pd.isna(rating_star):
                continue

            rating_star = int(rating_star)
            if rating_star not in STAR_BUCKETS:
                continue

            count_map.setdefault(product_key, self._empty_star_counts())
            rating_ids_map.setdefault(product_key, set())

            comment = str(getattr(row, "comment", "") or "").strip()
            if comment:
                count_map[product_key][rating_star] += 1

            rating_id = self._normalize_id(getattr(row, "rating_id", ""))
            if rating_id:
                rating_ids_map[product_key].add(rating_id)

        return count_map, rating_ids_map

    def _is_item_completed(self, row, sampled_counts):
        for star in STAR_BUCKETS:
            total_reviews = pd.to_numeric(row.get(f"star_{star}", -1), errors="coerce")
            if pd.isna(total_reviews) or int(total_reviews) < 0:
                return False

            expected_count = min(int(total_reviews), self.reviews_per_star_sample)
            if sampled_counts.get(star, 0) < expected_count:
                return False

        return True

    def _hydrate_existing_progress(self, df_products, count_map):
        frame = df_products.copy()
        for index, row in frame.iterrows():
            product_key = self._product_key(row.get("itemid"), row.get("shopid"))
            sampled_counts = count_map.get(product_key, self._empty_star_counts())

            for star in STAR_BUCKETS:
                frame.at[index, f"review_sampled_star_{star}"] = sampled_counts.get(star, 0)

            frame.at[index, "review_samples_done"] = int(self._is_item_completed(row, sampled_counts))

        return frame

    def _update_product_progress(self, df_products, row_index, star_counts, sampled_counts):
        for star in STAR_BUCKETS:
            df_products.at[row_index, f"star_{star}"] = int(star_counts.get(star, 0))
            df_products.at[row_index, f"review_sampled_star_{star}"] = int(sampled_counts.get(star, 0))

        df_products.at[row_index, "review_samples_done"] = int(
            all(
                sampled_counts.get(star, 0) >= self._target_samples_for_star(star_counts, star)
                for star in STAR_BUCKETS
            )
        )

    def _init_browser(self):
        co = ChromiumOptions()
        if runtime.chrome_path:
            co.set_browser_path(runtime.chrome_path)

        co.set_local_port(runtime.chrome_port)
        co.set_user_data_path(str(runtime.paths.profile_dir))
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--no-sandbox')

        page = ChromiumPage(co)
        page.run_js("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.set.window.max()
        page.get("https://shopee.vn/")

        print("\n" + "=" * 60)
        print("🚀 CHẾ ĐỘ CẬP NHẬT STAR DISTRIBUTION + REVIEW SAMPLES")
        print("→ Đăng nhập nếu bị đăng xuất")
        print("→ Giải CAPTCHA nếu có")
        input(">>> NHẤN ENTER KHI ĐÃ SẴN SÀNG <<<")
        print("=" * 60 + "\n")
        self.items_done = 0
        return page

    def _run_js(self, js: str):
        try:
            return self.page.run_js(js)
        except Exception as error:
            logger.error("run_js error: %s", error)
            return None

    def _is_blocked_url(self, url):
        current_url = str(url or "").lower()
        return '/buyer/login' in current_url or '/verify/' in current_url

    def _is_blocked_page(self):
        html_lower = str(self.page.html or "").lower()
        blocked_markers = [
            'trang không khả dụng',
            'bạn vui lòng đăng nhập lại',
            'vui lòng đăng nhập lại hoặc trở về trang chủ nhé',
            'please log in again',
            'page is not available',
        ]
        return any(marker in html_lower for marker in blocked_markers)

    def _ensure_product_page_ready(self, product_url, itemid):
        for attempt in range(1, 4):
            logger.info("Mở trang sản phẩm %s | attempt=%s", itemid, attempt)
            self.page.get(product_url)
            time.sleep(random.uniform(3, 4))

            current_url = str(self.page.url or "")
            logger.info("Current URL: %s", current_url)

            if not self._is_blocked_url(current_url) and not self._is_blocked_page():
                return True

            print("\n" + "!" * 50)
            print(f"⚠️ Shopee đang chặn hoặc redirect login cho item {itemid}")
            print(f"URL hiện tại: {current_url}")
            if self._is_blocked_page():
                print("Trang hiện tại báo 'Trang không khả dụng' và yêu cầu đăng nhập lại.")
            print("Hãy xử lý verify/login trong cửa sổ Chrome, sau đó mở lại đúng trang sản phẩm.")
            input(">>> Khi trang sản phẩm đã mở xong, nhấn ENTER <<<")
            print("!" * 50 + "\n")

        return False

    def _wait_for_reviews_visible(self, requested_star=None):
        wanted_star = "null" if requested_star is None else str(int(requested_star))
        for _ in range(5):
            logger.info("Đang tìm vùng review trên DOM%s...", f" cho {requested_star}★" if requested_star else "")
            state = self._run_js(f"""
            (() => {{
                const reviewRoot =
                    document.querySelector('.product-ratings') ??
                    Array.from(document.querySelectorAll('div, section')).find((element) =>
                        /ĐÁNH GIÁ SẢN PHẨM/i.test(element.textContent ?? '')
                    ) ??
                    null;

                if (reviewRoot) {{
                    reviewRoot.scrollIntoView({{behavior: 'instant', block: 'start'}});
                }} else {{
                    window.scrollBy(0, Math.max(window.innerHeight, 900));
                }}

                const filterTexts = Array.from(document.querySelectorAll('.product-rating-overview__filter'))
                    .map((element) => element.textContent?.trim() ?? '')
                    .filter(Boolean);
                const activeFilterText =
                    document.querySelector('.product-rating-overview__filter--active')?.textContent?.trim() ?? null;
                const targetFilterText =
                    typeof {wanted_star} === 'number'
                        ? filterTexts.find((text) => new RegExp(`^\\s*${{Number({wanted_star})}}\\s*Sao\\b`, 'i').test(text)) ?? null
                        : null;
                const totalFilterText =
                    filterTexts.find((text) => /^\\s*(t.t c.|all)\\b/i.test(text)) ?? null;
                const reviewCount = document.querySelectorAll(
                    '.shopee-product-comment-list > div[data-cmtid], .shopee-product-comment-list > div.q2b7Oq'
                ).length;
                const reviewText = reviewRoot?.textContent ?? document.body?.innerText ?? '';
                const hasNoReviewText =
                    /chưa có đánh giá|không có đánh giá|không tìm thấy đánh giá|hiện chưa có đánh giá|no reviews|no ratings/i.test(reviewText);

                return {{
                    url: window.location.href,
                    reviewCount,
                    hasReviewRoot: Boolean(reviewRoot),
                    hasNoReviewText,
                    activeFilterText,
                    targetFilterText,
                    totalFilterText
                }};
            }})()
            """)

            if not state:
                time.sleep(2)
                continue

            current_url = str(state.get("url", "")).lower()
            if self._is_blocked_url(current_url):
                return "blocked", state

            if int(state.get("reviewCount", 0) or 0) > 0:
                return "ready", state

            if state.get("hasNoReviewText"):
                return "empty", state

            self._auto_reach_review_section()
            time.sleep(2)

        return "not_found", state or {}

    def _start_review_listener(self):
        try:
            self.page.listen.start(LISTEN_PATH)
        except Exception as error:
            logger.warning("Không start được listener review: %s", error)

    def _clear_review_listener(self):
        try:
            self.page.listen.clear()
        except Exception:
            pass

    def _collect_review_packets(self, idle_timeout=4, max_packets=8):
        packets = []
        for _ in range(max_packets):
            try:
                packet = self.page.listen.wait(timeout=idle_timeout)
            except Exception:
                packet = None
            if not packet:
                break
            if getattr(packet.request, "method", "") == "OPTIONS":
                continue
            packets.append(packet)
        return packets

    def _listen_for_ratings_once(self, itemid, shopid, star=None, offset=0, limit=6, timeout=8):
        item_text = self._normalize_id(itemid)
        shop_text = self._normalize_id(shopid)
        filter_value = str(star) if star else "0"
        url = (
            "https://shopee.vn/api/v2/item/get_ratings"
            f"?itemid={item_text}"
            f"&shopid={shop_text}"
            f"&filter={filter_value}"
            f"&limit={int(limit)}"
            f"&offset={int(offset)}"
            "&type=0"
        )
        url_json = json.dumps(url)

        try:
            self.page.listen.start(LISTEN_PATH)
            self.page.listen.clear()
        except Exception as error:
            logger.warning("Không start được listener review: %s", error)
            return None

        js = f"""
        (() => {{
            try {{
                const xhr = new XMLHttpRequest();
                xhr.open('GET', {url_json}, true);
                xhr.setRequestHeader('Accept', 'application/json, text/plain, */*');
                xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
                xhr.send(null);
                return true;
            }} catch (error) {{
                return error?.message || String(error);
            }}
        }})()
        """
        trigger_result = self._run_js(js)
        if trigger_result not in {True, None}:
            logger.warning("Không trigger được request get_ratings: %s", trigger_result)
            return None

        try:
            packet = self.page.listen.wait(timeout=timeout)
        except Exception:
            packet = None
        finally:
            self._clear_review_listener()

        if not packet:
            return None

        try:
            payload = packet.response.body
        except Exception as error:
            logger.warning("Không đọc được response body từ packet: %s", error)
            return None

        if isinstance(payload, dict):
            return payload
        return None

    def _fetch_reviews_via_browser(self, itemid, shopid, star=None, offset=0, limit=6):
        """
        Trigger Shopee's get_ratings request in the browser, then capture the
        real network response via DrissionPage listener.
        """
        payload = self._listen_for_ratings_once(
            itemid=itemid,
            shopid=shopid,
            star=star,
            offset=offset,
            limit=limit,
        )
        if payload is not None:
            return payload
        return {"__client_error": "No response"}

    def _fetch_reviews_for_star_via_browser(self, itemid, shopid, star, max_reviews=5):
        """
        Fetch reviews for a specific star rating using browser-backed XHR.
        Returns list of review dicts and star_counts if available.
        """
        reviews = []
        star_counts = None
        offset = 0
        page_size = 15  # Shopee typically allows up to 50
        max_pages = 3

        for page_num in range(max_pages):
            if len(reviews) >= max_reviews:
                break

            response = self._fetch_reviews_via_browser(itemid, shopid, star, offset, page_size)

            if not response or response.get('__client_error'):
                error_msg = response.get('__client_error', 'Unknown error') if response else 'No response'
                status = response.get('__status') if isinstance(response, dict) else None
                if status in {403, 429}:
                    logger.warning("Shopee rating API returned HTTP %s", status)
                logger.warning("Browser XHR request failed: %s", error_msg)
                break

            error_code = response.get('error', 0)
            if error_code == 90309999:
                logger.warning("Session rejected (error 90309999) - need login/verify")
                return None, None  # Signal that session is invalid

            if error_code != 0:
                logger.warning("Shopee API error %s: %s", error_code, response.get('error_msg', ''))
                break

            data = response.get('data', {})

            # Extract star counts from first response
            if star_counts is None:
                summary = data.get('item_rating_summary', {})
                rating_count = summary.get('rating_count', [])
                if len(rating_count) >= 6:
                    star_counts = {
                        1: int(rating_count[1] or 0),
                        2: int(rating_count[2] or 0),
                        3: int(rating_count[3] or 0),
                        4: int(rating_count[4] or 0),
                        5: int(rating_count[5] or 0),
                    }

            ratings = data.get('ratings', [])
            if not ratings:
                break

            reviews.extend(ratings)
            offset += len(ratings)

            if len(ratings) < page_size:
                break

            time.sleep(random.uniform(0.5, 1.0))

        return reviews[:max_reviews], star_counts

    def _extract_star_counts_from_packet(self, payload):
        summary = payload.get("data", {}).get("item_rating_summary", {})
        rating_count = summary.get("rating_count", [])
        if len(rating_count) >= 6:
            return {
                1: int(rating_count[1] or 0),
                2: int(rating_count[2] or 0),
                3: int(rating_count[3] or 0),
                4: int(rating_count[4] or 0),
                5: int(rating_count[5] or 0),
            }
        return None

    def _extract_reviews_from_packets(self, packets):
        reviews = []
        star_counts = None
        for packet in packets:
            try:
                payload = packet.response.body
            except Exception:
                payload = None
            if not isinstance(payload, dict):
                continue
            if star_counts is None:
                star_counts = self._extract_star_counts_from_packet(payload)
            reviews.extend(payload.get("data", {}).get("ratings", []) or [])
        return star_counts, reviews

    def _scroll_review_section(self):
        for _ in range(4):
            self._run_js("""
            (() => {
                const reviewRoot =
                    document.querySelector('.product-ratings') ??
                    Array.from(document.querySelectorAll('div, section')).find((element) =>
                        /ĐÁNH GIÁ SẢN PHẨM/i.test(element.textContent ?? '')
                    );
                if (reviewRoot) {
                    reviewRoot.scrollIntoView({behavior: 'instant', block: 'start'});
                } else {
                    window.scrollBy(0, Math.max(window.innerHeight, 900));
                }
            })()
            """)
            time.sleep(1.5)

    def _click_review_anchor(self):
        clicked = self._run_js("""
        (() => {
            const clickable = Array.from(document.querySelectorAll('button, a, div'))
                .find((element) => /đánh giá|ratings?|reviews?/i.test((element.textContent || '').trim()));
            if (!clickable || clickable.offsetParent === null) return false;
            clickable.click();
            return true;
        })()
        """)
        if clicked:
            logger.info("Đã thử click anchor/tab đánh giá.")
            time.sleep(2)
        return bool(clicked)

    def _auto_reach_review_section(self):
        logger.info("Tự động cuộn tới vùng review...")
        self._click_review_anchor()

        for step in range(12):
            state = self._run_js("""
            (() => {
                const reviewRoot =
                    document.querySelector('.product-ratings') ??
                    Array.from(document.querySelectorAll('div, section')).find((element) =>
                        /ĐÁNH GIÁ SẢN PHẨM/i.test(element.textContent ?? '')
                    ) ??
                    null;
                const reviewCount = document.querySelectorAll(
                    '.shopee-product-comment-list > div[data-cmtid], .shopee-product-comment-list > div.q2b7Oq'
                ).length;
                const bodyText = (document.body?.innerText ?? '').slice(0, 4000);
                if (reviewRoot) {
                    reviewRoot.scrollIntoView({behavior: 'instant', block: 'start'});
                } else {
                    window.scrollBy(0, Math.max(window.innerHeight * 0.9, 700));
                }
                return {
                    hasReviewRoot: Boolean(reviewRoot),
                    reviewCount,
                    foundTitle: /ĐÁNH GIÁ SẢN PHẨM|ratings?|reviews?/i.test(bodyText)
                };
            })()
            """)
            time.sleep(1.2)
            logger.info(
                "Auto-scroll step=%s | review_root=%s review_count=%s title=%s",
                step + 1,
                bool((state or {}).get("hasReviewRoot")),
                int((state or {}).get("reviewCount", 0) or 0),
                bool((state or {}).get("foundTitle")),
            )
            if state and (state.get("hasReviewRoot") or int(state.get("reviewCount", 0) or 0) > 0):
                return True
        return False

    def _extract_star_counts_from_dom(self):
        result = self._run_js("""
        (() => {
            const out = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
            const filters = Array.from(document.querySelectorAll('.product-rating-overview__filter'));
            for (const filter of filters) {
                const text = (filter.textContent || '').trim();
                const match = text.match(/^(\\d)\\s*Sao.*?(\\d[\\d.,]*)/i);
                if (!match) continue;
                const star = Number(match[1]);
                const count = Number((match[2] || '').replace(/[^\\d]/g, '')) || 0;
                if (star >= 1 && star <= 5) out[star] = count;
            }
            return out;
        })()
        """)
        if not isinstance(result, dict):
            return self._empty_star_counts()
        counts = self._empty_star_counts()
        for star in STAR_BUCKETS:
            counts[star] = int(result.get(str(star), result.get(star, 0)) or 0)
        return counts

    def _activate_star_filter(self, star):
        clicked = self._run_js(f"""
        (() => {{
            const filters = Array.from(document.querySelectorAll('.product-rating-overview__filter'));
            const matcher = new RegExp(`^\\s*{int(star)}\\s*Sao\\b`, 'i');
            const target = filters.find((element) => matcher.test(element.textContent?.trim() ?? ''));
            if (!target) return false;
            target.click();
            return true;
        }})()
        """)
        if not clicked:
            return False
        time.sleep(2)
        self._go_to_first_review_page()
        time.sleep(1)
        return True

    def _go_to_first_review_page(self):
        clicked = self._run_js("""
        (() => {
            const buttons = Array.from(document.querySelectorAll('.product-ratings button'))
                .filter((button) => !button.disabled && button.offsetParent !== null);
            const activePageOne = buttons.find((button) =>
                button.innerText?.trim() === '1' && String(button.className ?? '').includes('shopee-button-solid')
            );
            if (activePageOne) return false;
            const firstPageButton = buttons.find((button) => button.innerText?.trim() === '1');
            if (!firstPageButton) return false;
            firstPageButton.click();
            return true;
        })()
        """)
        if clicked:
            time.sleep(1.5)

    def _click_next_review_page(self, previous_first_review_key):
        clicked = self._run_js(f"""
        (() => {{
            const candidates = Array.from(document.querySelectorAll('.product-ratings button'))
                .filter((button) => !button.disabled && button.offsetParent !== null);
            const nextButton = candidates.find((button) =>
                String(button.className ?? '').includes('shopee-icon-button--right')
            );
            if (!nextButton) return false;
            nextButton.click();
            return true;
        }})()
        """)
        if not clicked:
            return False

        time.sleep(2)
        return True

    def _review_to_row(self, itemid, shopid, star, review):
        ctime = review.get("ctime", 0) or 0
        code = self._product_code(itemid, shopid)
        t_ctime = ""
        if ctime:
            try:
                t_ctime = datetime.datetime.utcfromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                t_ctime = ""
        elif review.get("time_line"):
            t_ctime = str(review.get("time_line") or "").strip()

        product_items_raw = review.get("product_items") or []
        if product_items_raw and isinstance(product_items_raw[0], dict):
            product_items = ", ".join(
                product_item.get("model_name", "")
                for product_item in product_items_raw
                if product_item.get("model_name")
            )
        else:
            product_items = ", ".join(str(product_item).strip() for product_item in product_items_raw if str(product_item).strip())

        return {
            "code": code,
            "itemid": itemid,
            "shopid": shopid,
            "rating_star": star,
            "sample_index": 0,
            "rating_id": self._normalize_rating_id(review, itemid, shopid, star),
            "author_username": review.get("author_username", ""),
            "like_count": review.get("like_count", 0),
            "ctime": ctime,
            "t_ctime": t_ctime,
            "comment": (review.get("comment") or "").strip(),
            "product_items": product_items,
            "insert_date": self.today_date,
        }

    def _crawl_item_reviews(self, itemid, shopid, existing_counts, seen_rating_ids):
        product_url = f"https://shopee.vn/product/{int(shopid)}/{int(itemid)}"
        if not self._ensure_product_page_ready(product_url, itemid):
            logger.warning("Không đưa được item %s về trang sản phẩm hợp lệ.", itemid)
            return False, None, None

        html_lower = (self.page.html or "").lower()
        if 'captcha' in html_lower or 'verify' in html_lower or self._is_blocked_page():
            print("\n" + "!" * 50)
            print("⚠️ Trang hiện tại còn dấu hiệu CAPTCHA / VERIFY.")
            if self._is_blocked_page():
                print("⚠️ Hoặc Shopee đã trả về trang 'Trang không khả dụng' do session hết hạn.")
            print("Hãy xử lý trên Chrome, mở lại đúng trang sản phẩm.")
            input(">>> Khi trang sản phẩm đã mở lại được, nhấn ENTER <<<")
            print("!" * 50 + "\n")

        logger.info("Sử dụng browser session + XHR để fetch reviews...")
        sample_rows = []
        known_rating_ids = set(seen_rating_ids)
        star_counts = None
        xhr_failed = False

        for star in STAR_BUCKETS:
            need_count = self.reviews_per_star_sample
            existing_count = existing_counts.get(star, 0)

            if existing_count >= need_count:
                logger.info("  [%s★] đã đủ %s/%s review mẫu.", star, existing_count, need_count)
                continue

            reviews, counts = self._fetch_reviews_for_star_via_browser(itemid, shopid, star, max_reviews=need_count * 2)

            if reviews is None:
                return False, None, None

            if not reviews and counts is None and existing_count < need_count:
                xhr_failed = True
                break

            if counts and star_counts is None:
                star_counts = counts

            collected_new = 0
            for review in (reviews or []):
                if existing_count + collected_new >= need_count:
                    break

                comment = (review.get("comment") or "").strip()
                if not comment:
                    continue

                api_star = int(review.get("rating_star") or 0)
                if api_star != star:
                    continue

                rating_id = self._normalize_rating_id(review, itemid, shopid, star)
                if rating_id in known_rating_ids:
                    continue

                known_rating_ids.add(rating_id)
                collected_new += 1
                sample_rows.append(self._review_to_row(itemid, shopid, star, review))

            logger.info("  [%s★] lấy được %s review mẫu (target: %s)", star, collected_new, need_count - existing_count)
            time.sleep(random.uniform(*SLEEP_STARS))

        # If we couldn't get star_counts from API, try DOM
        if star_counts is None:
            star_counts = self._extract_star_counts_from_dom()

        if xhr_failed and not sample_rows and star_counts == self._empty_star_counts():
            logger.warning("XHR mode không lấy được review, fallback to packet listener")
            return self._crawl_item_reviews_packet_mode(itemid, shopid, existing_counts, seen_rating_ids)

        return True, star_counts, sample_rows

    def _crawl_item_reviews_packet_mode(self, itemid, shopid, existing_counts, seen_rating_ids):
        """Fallback method using packet listener (less reliable)."""
        self._start_review_listener()
        self._clear_review_listener()
        self._auto_reach_review_section()
        review_state, _ = self._wait_for_reviews_visible()
        if review_state in {"blocked", "not_found"}:
            return False, None, None
        if review_state == "empty":
            star_counts = self._empty_star_counts()
            return True, star_counts, []

        initial_packets = self._collect_review_packets()
        packet_star_counts, _ = self._extract_reviews_from_packets(initial_packets)
        star_counts = packet_star_counts or self._extract_star_counts_from_dom()

        sample_rows = []
        known_rating_ids = set(seen_rating_ids)

        for star in STAR_BUCKETS:
            target_count = self._target_samples_for_star(star_counts, star)
            existing_count = existing_counts.get(star, 0)

            if existing_count >= target_count:
                logger.info("  [%s★] đã đủ %s/%s review mẫu.", star, existing_count, target_count)
                continue

            collected_new = 0
            page_count = 0

            self._clear_review_listener()
            if not self._activate_star_filter(star):
                logger.warning("  [%s★] không bấm được filter sao.", star)
                continue

            self._auto_reach_review_section()
            filter_state, _ = self._wait_for_reviews_visible(star)
            if filter_state == "blocked":
                return False, None, None
            if filter_state == "empty":
                logger.info("  [%s★] không có review.", star)
                continue

            while existing_count + collected_new < target_count and page_count < MAX_DOM_PAGES_PER_STAR:
                packets = self._collect_review_packets()
                _, reviews = self._extract_reviews_from_packets(packets)
                if not reviews:
                    break

                for review in reviews:
                    if existing_count + collected_new >= target_count:
                        break

                    comment = (review.get("comment") or "").strip()
                    if not comment:
                        continue

                    api_star = int(review.get("rating_star") or 0)
                    if api_star != star:
                        continue

                    rating_id = self._normalize_rating_id(review, itemid, shopid, star)
                    if rating_id in known_rating_ids:
                        continue

                    known_rating_ids.add(rating_id)
                    collected_new += 1
                    sample_rows.append(self._review_to_row(itemid, shopid, star, review))

                logger.info(
                    "  [%s★] review mẫu: %s/%s",
                    star,
                    existing_count + collected_new,
                    target_count,
                )

                page_count += 1
                if existing_count + collected_new >= target_count:
                    break

                self._clear_review_listener()
                if not self._click_next_review_page(None):
                    break
                time.sleep(random.uniform(*SLEEP_PAGES))

            time.sleep(random.uniform(*SLEEP_STARS))

        return True, star_counts, sample_rows

    def __call__(self, df_products):
        all_products = load_csv(self.pdp_path) if self.pdp_path.exists() else df_products.copy()
        all_products = self._ensure_product_columns(all_products)
        review_columns = list(all_products.columns)

        reviews_df = self._load_existing_reviews()
        review_count_map, review_id_map = self._build_review_cache(reviews_df)
        all_products = self._hydrate_existing_progress(all_products, review_count_map)

        working_df = all_products
        if runtime.review_itemids:
            item_keys = {str(itemid) for itemid in runtime.review_itemids}
            working_df = working_df[
                working_df['itemid'].apply(lambda value: self._normalize_id(value) in item_keys)
            ]

        if runtime.product_limit:
            working_df = working_df.iloc[:runtime.product_limit]

        if runtime.review_start_index:
            working_df = working_df.iloc[runtime.review_start_index:]

        logger.info(
            "Review run config | pending_only=%s skip_sampled=%s item_filter=%s start_index=%s limit=%s per_star=%s",
            runtime.review_only_pending,
            runtime.review_skip_sampled,
            sorted(runtime.review_itemids) if runtime.review_itemids else [],
            runtime.review_start_index,
            runtime.product_limit,
            self.reviews_per_star_sample,
        )

        self.page = self._init_browser()

        try:
            for row_index, row in working_df.iterrows():
                itemid = row.get('itemid')
                shopid = row.get('shopid')

                if pd.isna(itemid) or pd.isna(shopid):
                    continue

                product_key = self._product_key(itemid, shopid)
                sampled_counts = review_count_map.get(product_key, self._empty_star_counts())
                already_done = self._is_item_completed(all_products.loc[row_index], sampled_counts)
                if (runtime.review_only_pending or runtime.review_skip_sampled) and already_done:
                    continue

                logger.info(f"Đang quét review SP: {itemid}")
                result_ok, star_counts, sample_rows = self._crawl_item_reviews(
                    itemid=itemid,
                    shopid=shopid,
                    existing_counts=sampled_counts,
                    seen_rating_ids=review_id_map.get(product_key, set()),
                )

                if result_ok is False:
                    print("\n" + "!" * 50)
                    print("⚠️ Có thể bị chặn / CAPTCHA. Xử lý trên Chrome rồi nhấn ENTER...")
                    input()
                    print("!" * 50 + "\n")
                    self.page.get("https://shopee.vn/")
                    time.sleep(3)
                    result_ok, star_counts, sample_rows = self._crawl_item_reviews(
                        itemid=itemid,
                        shopid=shopid,
                        existing_counts=sampled_counts,
                        seen_rating_ids=review_id_map.get(product_key, set()),
                    )

                if result_ok is False or star_counts is None:
                    logger.warning(f"SP {itemid}: không lấy được review sau khi retry, bỏ qua để lần sau chạy lại.")
                    continue

                if sample_rows:
                    reviews_df = upsert_dataframe(
                        reviews_df,
                        sample_rows,
                        columns=REVIEW_COLUMNS,
                        key_columns=["code", "rating_id", "rating_star"],
                    )
                    reviews_df = self._reindex_review_samples(reviews_df)
                    save_csv(self.reviews_path, reviews_df, REVIEW_COLUMNS)
                    review_count_map, review_id_map = self._build_review_cache(reviews_df)

                sampled_counts = review_count_map.get(product_key, self._empty_star_counts())
                self._update_product_progress(all_products, row_index, star_counts, sampled_counts)
                save_csv(self.pdp_path, all_products, review_columns)

                logger.info(
                    "✅ Star counts: %s | Sample comments: %s | Saved -> %s",
                    star_counts,
                    sampled_counts,
                    self.reviews_path.name,
                )

                self.items_done += 1
                if self.items_done > 0 and self.items_done % self.refresh_every == 0:
                    logger.info("🔄 Refresh session...")
                    self.page.get("https://shopee.vn/")
                    time.sleep(random.uniform(5, 10))

                time.sleep(random.uniform(*SLEEP_ITEMS))

        except KeyboardInterrupt:
            logger.info("Dừng thủ công. Dữ liệu đã lưu đến sản phẩm cuối cùng.")
        except Exception as error:
            logger.error(f"Lỗi hệ thống: {error}")
        finally:
            try:
                if self.page:
                    self.page.quit()
            except Exception:
                pass

        return load_csv(self.pdp_path)


if __name__ == "__main__":
    pdp_path = runtime.paths.product_detail_file

    if pdp_path.exists():
        df_products = pd.read_csv(pdp_path)
        crawler = ReviewCrawler()
        crawler(df_products)
    else:
        print("Lỗi: Không tìm thấy file pdp_detail.csv. Hãy chạy Product Crawler trước!")
