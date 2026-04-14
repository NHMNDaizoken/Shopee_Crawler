import logging

from crawlers.shop_finder import ShopFinder
from crawlers.product_shop_finder import ProductShopFinder
from crawlers.shop_crawler import ShopDetailCrawler
from crawlers.product_crawler import ProductDetailCrawler
from crawlers.review_crawler import ReviewCrawler
from utils.runtime import runtime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("crawler_main.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def main():
    runtime.ensure_dirs()
    input_file = runtime.paths.shops_file

    logger.info(
        "Runtime config | shops=%s auto_find=%s discovery_mode=%s shop_limit=%s keywords=%s chrome_port=%s profile=%s product_limit=%s review_itemids=%s review_start=%s per_star=%s",
        input_file,
        runtime.auto_find_shops,
        runtime.shop_discovery_mode,
        runtime.shop_discovery_limit,
        runtime.shop_keywords,
        runtime.chrome_port,
        runtime.paths.profile_dir,
        runtime.product_limit,
        sorted(runtime.review_itemids) if runtime.review_itemids else [],
        runtime.review_start_index,
        runtime.reviews_per_star_sample,
    )

    if runtime.auto_find_shops:
        if not runtime.shop_keywords:
            logger.warning("SHOPEE_AUTO_FIND_SHOPS=1 nhưng SHOPEE_KEYWORDS đang rỗng, bỏ qua bước auto-find.")
        else:
            if runtime.shop_discovery_mode == "products":
                logger.info("Step 0: Auto-finding shops from product listings...")
                product_shop_finder = ProductShopFinder(
                    keywords=runtime.shop_keywords,
                    max_pages=runtime.max_shop_pages,
                    max_shops=runtime.shop_discovery_limit,
                )
                product_shop_finder()
            else:
                logger.info("Step 0: Auto-finding shops based on env keywords...")
                shop_finder = ShopFinder(keywords=runtime.shop_keywords, max_pages=runtime.max_shop_pages)
                shop_finder()
    else:
        logger.info("Step 0: Skip auto shop finder (set SHOPEE_AUTO_FIND_SHOPS=1 để bật).")

    if not input_file.exists():
        logger.error(f"❌ Không tìm thấy file {input_file}.")
        return

    with input_file.open("r", encoding="utf-8") as f:
        shop_usernames = [line.strip() for line in f if line.strip()]

    if not shop_usernames:
        logger.warning("⚠️ File shops.txt đang trống.")
        return

    logger.info(f"📋 Bắt đầu xử lý {len(shop_usernames)} shop từ file shops.txt.")

    # --- BƯỚC 2: CÀO THÔNG TIN CHI TIẾT SHOP (Lấy ShopID) ---
    logger.info("Step 1: Fetching SHOP DETAILS...")
    shop_crawler = ShopDetailCrawler()
    df_shops = shop_crawler(shop_usernames)

    if df_shops.empty:
        logger.error("❌ Không lấy được thông tin shop nào. Dừng chương trình.")
        return

    # --- BƯỚC 3: CÀO CHI TIẾT SẢN PHẨM ---
    logger.info("Step 2: Start fetching PRODUCTS from shops...")
    product_crawler = ProductDetailCrawler()
    df_products = product_crawler(df_shops)

    if df_products.empty:
        logger.warning("⚠️ Không có sản phẩm nào được cào. Dừng chương trình.")
        return

    # --- BƯỚC 4: LẤY CHI TIẾT MỨC SAO ---
    logger.info("Step 3: Start fetching STAR RATINGS + REVIEW SAMPLES for each product...")
    review_crawler = ReviewCrawler()
    review_crawler(df_products)

    # --- BƯỚC 5: TỔNG KẾT ---
    logger.info("=" * 50)
    logger.info("🎉 HOÀN THÀNH TOÀN BỘ QUY TRÌNH!")
    logger.info(f"📂 Star distribution được cập nhật tại: {runtime.paths.product_detail_file}")
    logger.info(f"📂 Review samples được lưu tại: {runtime.paths.review_samples_file}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
