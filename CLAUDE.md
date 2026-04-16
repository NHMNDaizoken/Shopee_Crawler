# Shopee Crawler - Development Guide

## Project Overview

Shopee Crawler is a data extraction pipeline that collects shop details and product information from Shopee.vn, with customer reviews handled separately via Chrome Extension.

- **Project Type**: Web Scraper / Data Collection Pipeline
- **Language**: Python (backend) + JavaScript (Chrome Extension)
- **Primary Use**: E-commerce data analysis, competitor monitoring
- **Status**: Active production system with resume/recovery support

---

## Build & Test Commands

### Setup
```bash
pip install -r requirements.txt
cp .env.example .env
echo "shop_name" > shops.txt
```

### Main Commands
```bash
python main.py
python merge_reviews.py --input-dir . --output data/merged_reviews.csv
```

### Debug
```bash
tail -f crawler_main.log
python -c "from utils.runtime import runtime; print(runtime.chrome_path)"
```

---

## Architecture

### Three-Phase Workflow

**Phase 1 - Python (Automated)**
- Step 0: Optional auto-shop discovery
- Step 1: Fetch shop metadata (async API)
- Step 2: Crawl product listings (browser)

**Phase 2 - Chrome Extension (Separate flow)**
- Load product CSV, auto-scrape reviews
- Download batch CSVs

**Phase 3 - Merge (Optional)**
- Consolidate all review batches
- Deduplicate and sort

### Project Structure

```
.
├── main.py                     # Phase 1 entry
├── merge_reviews.py            # Phase 3
├── requirements.txt
├── .env.example
├── crawlers/
│   ├── shop_crawler.py
│   ├── product_crawler.py
│   ├── review_crawler.py
│   └── csv_store.py
├── utils/
│   ├── runtime.py
│   └── utils.py
├── shopee-review-extension/
│   ├── manifest.json
│   ├── popup.html
│   ├── popup.js
│   └── background.js
└── data/                       # Outputs
```

### Key Technologies

| Component | Tech | Purpose |
|-----------|------|---------|
| Shop API | aiohttp | Async requests |
| Browser | DrissionPage | Automation |
| CSV | pandas | Data processing |
| Validation | pydantic | Schema validation |
| Extension | Chrome MV3 | Browser scraping |
| Config | python-dotenv | Env vars |

---

## Configuration

### Environment Variables

**Browser Setup**
- SHOPEE_CHROME_PATH: Chrome executable path
- SHOPEE_CHROME_PORT: Debug port (9222)
- SHOPEE_PROFILE_DIR: Chrome profile

**Shop Discovery (Optional)**
- SHOPEE_AUTO_FIND_SHOPS: Enable (0=no)
- SHOPEE_KEYWORDS: Pipe-separated
- SHOPEE_SHOP_DISCOVERY_MODE: users|products

**Product Crawling**
- SHOPEE_PRODUCT_LIMIT: Max products

### Output Files

- shop_detail.csv: Shop metadata
- pdp_detail.csv: Product metadata
- shopee_reviews_batch_N.csv: Batches
- merged_reviews.csv: Final output

---

## Core Modules

### ShopDetailCrawler

Fetches shop metadata with async requests.

1. Load existing shopids
2. Normalize identifiers
3. Build API URLs
4. Execute async (max 3, 1-2.5s delays)
5. Upsert with dedup on shopid

### ProductDetailCrawler

Crawls product listings via browser.

1. Load existing products
2. Configure Chrome
3. Listen for search_items API packets
4. Scroll to trigger lazy-load
5. Parse and extract items
6. Save per shop
7. Skip if complete

### ReviewCrawler

Standalone review crawler module kept outside the default `main.py` flow.
Use only when explicitly needed as a fallback or for ad hoc review sampling.

### merge_reviews.py

Consolidates review batches.

1. Glob search CSV files
2. Load with UTF-8-SIG
3. Concat DataFrames
4. Drop duplicates on rating_id
5. Sort and write

---

## CSV Utilities

- load_csv(path, columns): Load or create
- save_csv(path, rows, columns): Overwrite
- append_rows(path, rows, columns): Append
- upsert_csv(path, incoming, columns, keys): Merge/dedup

Dedup keys: Shop=[shopid], Product=[shopid,itemid], Reviews=[rating_id]

---

## Chrome Extension

### Purpose

Bypass anti-bot by scraping through browser session.

### How It Works

```javascript
await window.PlatformApi.FetchUtils.get(
  '/api/v2/item/get_ratings?itemid=X&shopid=Y&filter=5&limit=20'
);
```

Has full cookies/session, appears as real user.

### Modes

- Single Product: Navigate to product, click extension
- Batch from CSV: Load CSV, auto-scrapes all

### Rate Limiting

- 500ms between requests
- 1-2s between star levels

---

## Runtime Configuration

Singleton: runtime = RuntimeConfig()

**Responsibilities**:
- Load .env
- Auto-detect Chrome
- Build paths
- Parse env vars (bool, int, list, set)
- Create directories

**Key Methods**:
- _env_flag(name, default): Boolean
- _env_int(name, default): Integer
- detect_chrome_path(): Find Chrome
- ensure_dirs(): Create output dirs

---

## Workflows

### Fresh Start

```bash
pip install -r requirements.txt
cp .env.example .env
echo "shop1" > shops.txt
python main.py
# Manual: Load extension, scrape
python merge_reviews.py --input-dir . --output data/final.csv
```

### Resume After Interrupt

```bash
python main.py  # Reloads, skips known, resumes
```

### Auto-Discovery

```bash
SHOPEE_AUTO_FIND_SHOPS=1 SHOPEE_KEYWORDS="ao thun|giay" python main.py
```

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| CAPTCHA | Bot detection | Solve manually |
| API error 90309999 | Session expired | Refresh, log in |
| Extension blocked | Rate limit | Wait 5-10 min |
| shops.txt missing | Not created | echo "shop" > shops.txt |
| Chrome not found | Invalid path | Set in .env |
| Browser hangs | Crashed | Kill Chrome, restart |

### Debug

```bash
python -c "from utils.runtime import runtime; print(runtime.chrome_path)"
tail -100 crawler_main.log | grep ERROR
```

---

## Performance

- **Shop API**: 100 shops = 200-300s (5 min)
- **Product Browser**: 50/shop = 5-10 min
- **Extension Batch**: 200 products = 30-50 min

### Optimization

- Use SHOPEE_PRODUCT_LIMIT (test)
- Parallel extension batches (2-4x)

---

## Adding Features

**New Environment Variables**:
1. Add to .env.example
2. Parse in utils/runtime.py
3. Use via runtime.<var_name>

**New Crawler Step**:
1. Create crawlers/my_crawler.py
2. Add to main.py
3. Use csv_store for I/O

---

## Design Principles

1. Resume-safe: Upsert operations
2. Rate-limited: Random delays
3. Session-persistent: Chrome profile survives
4. Stateful: CSV tracks progress
5. Modular: Independent steps
6. CSV-focused: Excel compatible
7. Low-dependency: Standard libs

---

## Documentation

- User Guide: README.md (Vietnamese)
- Extension: shopee-review-extension/README.md

---

## Technologies

- DrissionPage: https://gitee.com/g1879/DrissionPage
- Chrome MV3: https://developer.chrome.com/docs/extensions/
- Pandas: https://pandas.pydata.org/
- aiohttp: https://docs.aiohttp.org/
- Pydantic: https://docs.pydantic.dev/
