# 🛍️ Shopee Review Scraper - Chrome Extension

Chrome Extension để cào reviews từ Shopee **không bị chặn** vì chạy trong browser context thật.

## ✨ Tính năng

- ✅ **Cào review 1-5 sao** với số lượng tùy chỉnh (mặc định 5 mỗi sao)
- ✅ **Dùng PlatformApi.FetchUtils** - giống như request từ user thật
- ✅ **Không bị Shopee chặn** - chạy trong browser context
- ✅ **Export CSV** với BOM header (tương thích Excel)
- ✅ **UI đẹp** với progress tracking

## 🚀 Cài đặt

1. **Clone/Download folder này**:
   ```
   shopee-review-extension/
   ```

2. **Mở Chrome Extensions**:
   - Gõ `chrome://extensions/` vào address bar
   - Bật **Developer mode** (góc phải trên)

3. **Load extension**:
   - Click **Load unpacked**
   - Chọn folder `shopee-review-extension`

4. **Xong!** Icon extension sẽ xuất hiện trên toolbar

## 📖 Cách dùng

### 1. Cào 1 sản phẩm

1. Mở trang sản phẩm Shopee bất kỳ:
   ```
   https://shopee.vn/product/{shopId}/{itemId}
   ```

2. Click icon extension hoặc nút floating 📝 góc phải dưới

3. Cấu hình:
   - **Reviews per star**: 5 (hoặc tùy chỉnh)
   - **Mode**: Current Product Page

4. Click **▶️ Start Scraping**

5. Đợi vài giây, khi xong click **📥 Download CSV**

### 2. Batch semi-auto từ CSV

1. Mở một tab Shopee bất kỳ và đảm bảo **đang đăng nhập**
2. Click icon extension
3. Chọn:
   - **Mode**: `Batch from CSV`
   - **CSV file**: chọn `data/pdp_detail.csv`
   - **Reviews per star**: thường để `5`
4. Click **▶️ Start Scraping**
5. Extension sẽ dùng **tab hiện tại** để đi từng URL sản phẩm
6. Nếu Shopee bắt đăng nhập/captcha:
   - xử lý trên tab đó
   - mở lại popup để xem trạng thái
   - batch sẽ dừng ở sản phẩm lỗi, không tự xóa progress
7. Khi chạy xong extension sẽ tự tải **1 file CSV gộp**

### 3. Output CSV

Format chuẩn hóa giống output mới của console script:

```csv
code,itemid,shopid,rating_star,sample_index,rating_id,author_username,like_count,ctime,t_ctime,comment,product_items,insert_date
24710134_3431453055,3431453055,24710134,5,1,12345678,user123,10,1634567890,"2021-10-18 12:34:50","Sản phẩm tốt!","Màu đen, Size M","2026-04-03 16:05:00"
```

`code` là mã sản phẩm chuẩn để dùng khi gộp nhiều file đã tải về.

## 🔧 Kỹ thuật

Extension dùng **PlatformApi.FetchUtils.get()** - API chính của Shopee web:

```javascript
const response = await window.PlatformApi.FetchUtils.get(
  '/api/v2/item/get_ratings?itemid=xxx&shopid=yyy&filter=5&limit=20'
);
```

**Ưu điểm**:
- Request đi từ browser thật → có đầy đủ cookies/session
- Shopee không phân biệt được với user thật
- Không cần selenium/puppeteer/playwright

## ⚠️ Lưu ý

- Extension chỉ hoạt động trên `*.shopee.vn`
- Cần đăng nhập Shopee trước khi dùng
- Có rate limit (500ms giữa các request, 1s giữa các sao)

## 📦 Files

```
shopee-review-extension/
├── manifest.json      # Extension config
├── background.js      # Service worker (xử lý download)
├── popup.html         # UI popup
├── popup.js           # Logic popup
├── content.js         # Content script (nút floating)
└── README.md          # Tài liệu này
```

## 🔄 So sánh với Python crawler

| Tiêu chí | Python | Chrome Extension |
|----------|--------|------------------|
| Bị Shopee chặn | ✅ Có | ❌ Không |
| Cần session setup | ✅ Có | ❌ Không (dùng session browser) |
| Tự động 100% | ✅ Có | ❌ Không, nhưng semi-auto ổn hơn |
| Batch nhiều SP | ✅ Có | ✅ Có, từ CSV |

## 💡 Gợi ý chạy thực tế

- Chạy theo lô 50-200 sản phẩm/lần
- Dùng đúng profile Chrome bạn vẫn dùng để login Shopee
- Nếu thấy Shopee bắt verify nhiều, dừng 5-10 phút rồi chạy tiếp lô sau

---

**Made with ❤️ to bypass Shopee anti-bot**
