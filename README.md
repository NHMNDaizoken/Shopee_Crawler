# Shopee Crawler

Thu thập dữ liệu shop, sản phẩm và đánh giá từ Shopee.vn.

---

## Tổng quan Flow

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                        SHOPEE CRAWLER PIPELINE                         │
 └─────────────────────────────────────────────────────────────────────────┘

 ╔═══════════════════════════════════════════════════════════════════════╗
 ║  PHASE 1 — Python Pipeline (tự động)                    python main.py  ║
 ╚═══════════════════════════════════════════════════════════════════════╝

    ┌──────────────┐
    │  shops.txt   │  Danh sách tên shop / shopid (nhập tay)
    └──────┬───────┘
           │
           ▼
    ┌──────────────────────────────────────────────────┐
    │  Step 1: Crawl Shop Details   (shop_crawler.py)  │
    │  ─────────────────────────────────────────────── │
    │  • Gọi API Shopee lấy thông tin shop             │
    │  • Async, tối đa 3 request đồng thời             │
    │  • Output: shopid, tên, follower, rating...      │
    └──────────────┬───────────────────────────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ shop_detail.csv │
          └────────┬────────┘
                   │
                   ▼
    ┌──────────────────────────────────────────────────┐
    │  Step 2: Crawl Products      (product_crawler.py)│
    │  ─────────────────────────────────────────────── │
    │  • Mở Chrome đến trang shop, lắng nghe API       │
    │  • Scroll trang để trigger load thêm sản phẩm    │
    │  • Output: itemid, tên, giá, đã bán, rating...   │
    └──────────────┬───────────────────────────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  pdp_detail.csv │
          └────────┬────────┘
                   │
                   ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║  PHASE 2 — Chrome Extension (bán tự động)                           ║
 ╚═══════════════════════════════════════════════════════════════════════╝

    ┌──────────────────────────────────────────────────┐
    │  Crawl Reviews        (shopee-review-extension/) │
    │  ─────────────────────────────────────────────── │
    │  • Load pdp_detail.csv vào extension             │
    │  • Extension tự mở từng trang sản phẩm           │
    │  • Scrape review 1-5 sao bằng API nội bộ Shopee  │
    │  • Tự nghỉ giữa các batch để tránh bị chặn       │
    │  • Auto download CSV sau mỗi batch                │
    └──────────────┬───────────────────────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────────┐
    │  shopee_reviews_batch_*.csv (nhiều)  │
    └──────────────┬───────────────────────┘
                   │
                   ▼
 ╔═══════════════════════════════════════════════════════════════════════╗
 ║  PHASE 3 — Merge Reviews (tự động)                                  ║
 ╚═══════════════════════════════════════════════════════════════════════╝

    ┌──────────────────────────────────────────────────┐
    │  merge_reviews.py                                │
    │  ─────────────────────────────────────────────── │
    │  • Gom tất cả file CSV review lại                 │
    │  • Loại trùng theo rating_id                      │
    │  • Sắp xếp theo shop → product → sao             │
    └──────────────┬───────────────────────────────────┘
                   │
                   ▼
          ┌────────────────────┐
          │ merged_reviews.csv │  ← Kết quả cuối cùng
          └────────────────────┘
```

### Flow tóm tắt

```
shops.txt ──► shop_detail.csv ──► pdp_detail.csv ──► [Extension] ──► merged_reviews.csv
  (shop)        (chi tiết shop)     (sản phẩm)       (review 1-5★)    (review gộp)
```

---

## Cài đặt

```bash
# 1. Cài dependencies
pip install -r requirements.txt

# 2. Copy file config
cp .env.example .env
# Sửa .env theo nhu cầu

# 3. Tạo file shops.txt (mỗi dòng 1 shop)
echo "coolmate.vn" > shops.txt
```

---

## Hướng dẫn sử dụng

### Phase 1 — Chạy Python Pipeline

```bash
python main.py
```

Pipeline tự động chạy 2 bước:
1. **Crawl shop** → `data/shop_detail.csv`
2. **Crawl sản phẩm** → `data/pdp_detail.csv`

> Chrome sẽ tự mở. Đăng nhập Shopee nếu chưa đăng nhập. Giải CAPTCHA thủ công khi được yêu cầu.

### Phase 2 — Crawl Review bằng Extension

```
1. Mở Chrome → chrome://extensions/ → Bật Developer mode
2. Click "Load unpacked" → chọn thư mục shopee-review-extension/
3. Mở extension → chọn "Batch from CSV"
4. Load file data/pdp_detail.csv
5. Click "Start Scraping" → đợi extension chạy
6. Lưu các file CSV được tự động download
```

### Phase 3 — Gộp Reviews

```bash
python merge_reviews.py --input-dir . --output data/all_reviews_merged.csv
```

---

## Biến môi trường

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `SHOPEE_CHROME_PORT` | `9222` | Port debug Chrome |
| `SHOPEE_AUTO_FIND_SHOPS` | `0` | `1` = tự tìm shop từ keyword |
| `SHOPEE_SHOP_DISCOVERY_MODE` | `users` | `users` hoặc `products` |
| `SHOPEE_KEYWORDS` | _(trống)_ | Keyword tìm shop, cách bởi `\|` |
| `SHOPEE_PRODUCT_LIMIT` | _(trống)_ | Giới hạn số sản phẩm crawl |
| `SHOPEE_REVIEWS_PER_STAR` | `5` | Số review mẫu mỗi mức sao |
| `SHOPEE_REVIEW_ONLY_PENDING` | `1` | Chỉ crawl sản phẩm chưa có review |
| `SHOPEE_REVIEW_SKIP_SAMPLED` | `1` | Bỏ qua sản phẩm đã lấy đủ mẫu |
| `SHOPEE_REVIEW_ITEMIDS` | _(trống)_ | Chỉ crawl các itemid cụ thể (phẩy cách) |
| `SHOPEE_REVIEW_START_INDEX` | `0` | Bắt đầu từ sản phẩm thứ N |

---

## File output

| File | Nội dung | Cột chính |
|------|----------|-----------|
| `data/shop_detail.csv` | Thông tin shop | `shopid`, `name`, `follower_count`, `rating_star` |
| `data/pdp_detail.csv` | Chi tiết sản phẩm + phân bổ sao | `shopid`, `itemid`, `name`, `price` |
| `data/all_reviews_merged.csv` | Tất cả review đã gộp | `rating_id`, `rating_star`, `comment` |

---

## Cấu trúc dự án

```
.
├── main.py                     # Entry point - chạy Phase 1
├── merge_reviews.py            # Phase 3 - gộp review CSV
├── shops.txt                   # Input: danh sách shop
├── .env.example                # Template biến môi trường
├── requirements.txt            # Python dependencies
│
├── crawlers/
│   ├── shop_crawler.py         # Step 1: Crawl thông tin shop (async API)
│   ├── product_crawler.py      # Step 2: Crawl sản phẩm (browser)
│   ├── shop_finder.py          # Auto-find shop qua tìm user
│   ├── product_shop_finder.py  # Auto-find shop qua tìm sản phẩm
│   ├── review_crawler.py       # Crawl review (fallback cho extension)
│   └── csv_store.py            # Tiện ích đọc/ghi CSV
│
├── utils/
│   ├── runtime.py              # Config tập trung (env, paths)
│   └── utils.py                # Timer decorator
│
├── shopee-review-extension/    # Chrome Extension crawl review
│   ├── manifest.json
│   ├── background.js           # Service worker: quản lý batch
│   ├── popup.html              # Giao diện extension
│   ├── popup.js                # Logic scrape + UI popup
│   └── content.js              # Floating button trên trang SP
│
└── data/                       # Thư mục output
    ├── shop_detail.csv
    ├── pdp_detail.csv
    └── all_reviews_merged.csv
```

---

## Xử lý lỗi thường gặp

| Lỗi | Cách xử lý |
|-----|-------------|
| **CAPTCHA xuất hiện** | Giải thủ công trong Chrome, nhấn Enter để tiếp tục |
| **Chuyển hướng trang login** | Đăng nhập Shopee, đợi 1-2 phút, chạy lại |
| **API error 90309999** | Session hết hạn → refresh Shopee, đăng nhập lại |
| **Gián đoạn giữa chừng** | Chạy lại `python main.py` — tự bỏ qua dữ liệu đã crawl |
| **Extension bị chặn** | Giải CAPTCHA, refresh trang, đặt lại Start row rồi chạy tiếp |

---

## Ghi chú

- Pipeline hỗ trợ **resume**: chạy lại sẽ tự bỏ qua dữ liệu đã có
- Dữ liệu được lưu **sau mỗi shop/sản phẩm**, nên gián đoạn không mất dữ liệu
- Extension chạy trong **session thật** của trình duyệt nên ít bị chặn hơn Python
- `merge_reviews.py` luôn **loại trùng** theo `rating_id`, gộp lại bao nhiêu lần cũng an toàn
