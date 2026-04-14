from utils.utils import timer

import logging
import datetime
import time
import pandas as pd
from pydantic import BaseModel, ConfigDict
from DrissionPage import ChromiumPage, ChromiumOptions
from crawlers.csv_store import load_csv, upsert_csv
from utils.runtime import runtime

logger = logging.getLogger(__name__)


class ItemParams(BaseModel):
    itemid: int | str | None = 0
    shopid: int | None = 0
    name: str | None = ""
    currency: str | None = "VND"
    stock: int | None = 0
    status: int | None = 0
    ctime: int | None = 0
    t_ctime: str | None = ""
    sold: int | None = 0
    historical_sold: int | None = 0
    liked_count: int | None = 0
    image_url: str | None = ""
    images_url: str | None = ""
    brand: str | None = ""
    cmt_count: int | None = 0
    item_status: str | None = ""
    price: int | None = 0
    price_min: int | None = 0
    price_max: int | None = 0
    price_before_discount: int | None = 0
    show_discount: int | None = 0
    raw_discount: int | None = 0
    tier_variations_option: str | None = ""
    rating_star_avg: float | None = 0.0
    item_type: int | None = 0
    is_adult: bool | None = False
    has_lowest_price_guarantee: bool | None = False
    is_official_shop: bool | None = False
    is_cc_installment_payment_eligible: bool | None = False
    is_non_cc_installment_payment_eligible: bool | None = False
    is_preferred_plus_seller: bool | None = False
    is_mart: bool | None = False
    is_on_flash_sale: bool | None = False
    is_service_by_shopee: bool | None = False
    shopee_verified: bool | None = False
    show_official_shop_label: bool | None = False
    show_shopee_verified_label: bool | None = False
    show_official_shop_label_in_title: bool | None = False
    show_free_shipping: bool | None = False
    insert_date: str | None = ""
    user_name: str | None = ""
    user_email: str | None = ""

    model_config = ConfigDict(extra="ignore")


class ProductDetailCrawler:
    def __init__(self):
        self.items_list = []
        self.today_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.product_limit = runtime.product_limit
        self.output_file = runtime.paths.product_detail_file

    def parse_items(self, info):
        """Hàm bóc tách dữ liệu JSON thành Object"""
        items = info.get("items") or info.get("data", {}).get("items", [])
        if not items: return

        for item_wrapper in items:
            try:
                item = item_wrapper.get("item_basic", {})
                if not item: continue

                dateArray = datetime.datetime.utcfromtimestamp(item.get("ctime", 0))
                transfor_time = dateArray.strftime("%Y-%m-%d %H:%M:%S")

                item_rating = item.get("item_rating", {})
                tier_variations = item.get("tier_variations", [])
                tier_options = tier_variations[0].get("options", []) if tier_variations else []

                base_img_url = "https://down-vn.img.susercontent.com/file/"
                image_hash = item.get("image", "")
                full_image_url = f"{base_img_url}{image_hash}" if image_hash else ""
                images_hash_list = item.get("images", [])
                full_images_url = ",".join([f"{base_img_url}{img}" for img in images_hash_list])

                item_info = ItemParams(
                    **item, t_ctime=transfor_time, insert_date=self.today_date,
                    image_url=full_image_url, images_url=full_images_url,
                    rating_star_avg=item_rating.get("rating_star", 0.0),
                    tier_variations_option=",".join(tier_options)
                )
                self.items_list.append(item_info.model_dump())
            except Exception as e:
                logger.error(f"Error parsing item: {e}")

    @timer
    def __call__(self, shop_detail):
        headers_list = list(ItemParams.model_fields.keys())
        self.items_list = []

        df_existing = load_csv(self.output_file, headers_list)
        existing_count_by_shop = {}
        if not df_existing.empty and 'shopid' in df_existing.columns:
            existing_count_by_shop = (
                df_existing['shopid']
                .dropna()
                .astype(str)
                .value_counts()
                .to_dict()
            )

        saved_count = len(df_existing)
        if self.product_limit:
            logger.info("Product crawl limit enabled: %s", self.product_limit)
            if saved_count >= self.product_limit:
                logger.info("pdp_detail.csv đã có %s dòng >= limit, bỏ qua crawl product.", saved_count)
                return df_existing

        logger.info("Configuring Chrome browser...")
        co = ChromiumOptions()
        if runtime.chrome_path:
            co.set_browser_path(runtime.chrome_path)

        co.set_local_port(runtime.chrome_port)
        co.set_user_data_path(str(runtime.paths.profile_dir))

        try:
            page = ChromiumPage(co)
            logger.info("Opening Shopee... YOU HAVE 15 SECONDS TO LOGIN (IF REQUIRED).")
            page.get("https://shopee.vn/")
            time.sleep(15)

            # Khởi động "tai nghe" bắt đúng gói tin API search
            page.listen.start('search_items')

            for row in shop_detail.itertuples():
                if self.product_limit and saved_count >= self.product_limit:
                    logger.info("Đã đạt product limit=%s, dừng crawl thêm shop.", self.product_limit)
                    break

                shop_id = getattr(row, 'shopid', None)
                shop_product_count = getattr(row, 'item_count', 0)
                if not shop_id: continue

                existing_shop_count = existing_count_by_shop.get(str(shop_id), 0)
                if shop_product_count and existing_shop_count >= int(shop_product_count):
                    logger.info(
                        "BỎ QUA SHOP ID %s: đã có %s/%s sản phẩm trong pdp_detail.csv.",
                        shop_id,
                        existing_shop_count,
                        int(shop_product_count),
                    )
                    continue

                logger.info(f"Processing shop ID: {shop_id} ({shop_product_count} items expected)")
                collected = 0
                page_num = 0

                # Dùng vòng lặp vô tận, chỉ dừng khi trang trắng
                while True:
                    url = f"https://shopee.vn/shop/{shop_id}/search?page={page_num}"
                    logger.info(f"Đang tải trang {page_num + 1}...")

                    page.listen.clear()
                    page.get(url)

                    # Cuộn từ từ để ép Shopee ném TẤT CẢ các gói tin ra
                    for _ in range(4):
                        time.sleep(1.5)
                        page.scroll.down(600)

                    # Chờ và hút TẤT CẢ các gói tin bắt được trong trang này
                    page_collected = 0
                    while True:
                        packet = page.listen.wait(timeout=5)
                        if not packet:
                            break  # Nếu 5s trôi qua không có gói tin nào bay ra -> Chắc chắn đã lấy hết gói tin của trang

                        if packet.request.method != 'OPTIONS':
                            try:
                                info = packet.response.body
                                if info and isinstance(info, dict):
                                    items = info.get("items") or info.get("data", {}).get("items", [])
                                    if items:
                                        self.parse_items(info)
                                        page_collected += len(items)
                            except Exception as e:
                                logger.error(f"Lỗi khi đọc gói tin: {e}")

                    # Tổng kết sau khi hút hết các gói tin trong 1 trang
                    if page_collected > 0:
                        collected += page_collected
                        logger.info(
                            f"   ✅ SUCCESS! Lấy được {page_collected} SP ở trang {page_num + 1}. (Tổng đã lấy: {collected}/{shop_product_count})")
                    else:
                        logger.info(
                            f"   🛑 Trang {page_num + 1} hoàn toàn trống. Đã cào sạch những SP đang hiển thị của Shop này.")
                        break  # Trang trống thì thoát, sang shop khác

                    # Nếu số lượng cào được đã lớn hơn hoặc bằng dự kiến thì cũng không cần lật trang nữa
                    if collected >= shop_product_count:
                        logger.info("   🏁 Đã đạt mức dự kiến của Shop.")
                        break

                    page_num += 1
                    time.sleep(3)

                # Lưu vào file sau khi xử lý xong mỗi shop để giữ an toàn dữ liệu
                if self.items_list:
                    rows_to_save = self.items_list
                    if self.product_limit and saved_count + len(rows_to_save) > self.product_limit:
                        keep_count = self.product_limit - saved_count
                        rows_to_save = rows_to_save[:keep_count]

                    df_save = pd.DataFrame(rows_to_save, columns=headers_list)
                    if not df_save.empty:
                        merged_df = upsert_csv(
                            self.output_file,
                            df_save,
                            columns=headers_list,
                            key_columns=["shopid", "itemid"],
                        )
                        saved_count = len(merged_df)
                        if 'shopid' in merged_df.columns:
                            existing_count_by_shop = (
                                merged_df['shopid']
                                .dropna()
                                .astype(str)
                                .value_counts()
                                .to_dict()
                            )
                        logger.info("Đã upsert %s sản phẩm. Tổng hiện tại: %s", len(df_save), saved_count)

                    self.items_list = []

                if self.product_limit and saved_count >= self.product_limit:
                    logger.info("Đã đạt product limit=%s sau shop %s.", self.product_limit, shop_id)
                    break

        except Exception as e:
            logger.error(f"Browser error: {e}")
        finally:
            try:
                if 'page' in locals(): page.quit()
            except Exception:
                pass

        return load_csv(self.output_file, headers_list)
