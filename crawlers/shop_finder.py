import os
import time
import logging
from DrissionPage import ChromiumPage, ChromiumOptions
from utils.runtime import runtime

logger = logging.getLogger(__name__)


class ShopFinder:
    def __init__(self, keywords, max_pages=1):
        self.keywords = keywords
        self.max_pages = max_pages
        self.project_root = str(runtime.paths.project_root)
        self.output_file = str(runtime.paths.shops_file)

    def __call__(self):
        co = ChromiumOptions()
        if runtime.chrome_path:
            co.set_browser_path(runtime.chrome_path)

        co.set_local_port(runtime.shop_finder_port)
        co.set_user_data_path(str(runtime.paths.profile_dir))

        logger.info("🚀 Khởi động công cụ TÌM SHOP TỰ ĐỘNG...")
        found_shops = set()

        try:
            page = ChromiumPage(co)
            page.set.window.max()
            page.get("https://shopee.vn/")
            time.sleep(5)
            page.listen.start('api/v4/search/search_user')

            for kw in self.keywords:
                logger.info(f"\n🔍 Đang tìm các shop bán: '{kw}'")
                for p in range(self.max_pages):
                    url = f"https://shopee.vn/search_user?keyword={kw}&page={p}"
                    page.listen.clear()
                    page.get(url)

                    for _ in range(5):
                        page.scroll.down(600)
                        time.sleep(1)

                    packet = page.listen.wait(timeout=5)
                    added_this_page = 0

                    try:
                        elements = page.eles('.shopee-search-user-item__nickname')
                        for ele in elements:
                            username = ele.text.replace('@', '').strip()
                            if username and username not in found_shops:
                                found_shops.add(username)
                                added_this_page += 1
                    except Exception:
                        pass

                    if added_this_page == 0 and packet and packet.request.method != 'OPTIONS':
                        logger.info(" -> Đọc từ API dự phòng...")
                        try:
                            raw_body = packet.response.body
                            if isinstance(raw_body, dict):
                                users = raw_body.get('data', {}).get('users', [])
                                for user in users:
                                    username = user.get('username')
                                    if username and username not in found_shops:
                                        found_shops.add(username)
                                        added_this_page += 1
                        except Exception as error:
                            logger.error(f"Lỗi phân tích JSON: {error}")

                    if added_this_page > 0:
                        logger.info(f" ✅ Đã lấy được {added_this_page} shop ở trang {p + 1}.")
                    else:
                        logger.warning(f" ⚠️ Trắng tay ở trang {p + 1}. Có thể trang đã hết shop.")

                    time.sleep(3)

        except Exception as error:
            logger.error(f"Lỗi trình duyệt ShopFinder: {error}")
        finally:
            try:
                if 'page' in locals():
                    page.quit()
            except Exception:
                pass

        if found_shops:
            existing_shops = set()
            if os.path.exists(self.output_file):
                with open(self.output_file, 'r', encoding='utf-8') as file:
                    existing_shops = set(line.strip() for line in file if line.strip())

            all_shops = existing_shops.union(found_shops)
            with open(self.output_file, 'w', encoding='utf-8') as file:
                for shop in sorted(all_shops):
                    file.write(f"{shop}\n")

            logger.info(
                f"\n💾 Đã lưu thành công! Thêm mới {len(found_shops)} shop. "
                f"Tổng cộng file shops.txt đang có {len(all_shops)} shop."
            )
        else:
            logger.warning("\n❌ Không tìm thêm được shop nào mới!")

        return list(found_shops)
