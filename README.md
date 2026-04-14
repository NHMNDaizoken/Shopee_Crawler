# Shopee Crawler

Crawl shop info, product details, and review samples from Shopee.vn.

## Overview

The project has **3 phases**:

```
Phase 1: Python Pipeline (automated)
  shops.txt -> shop_detail.csv -> pdp_detail.csv -> product_review_samples.csv

Phase 2: Chrome Extension (semi-automated)
  pdp_detail.csv -> extension scrapes reviews per product -> multiple CSV files

Phase 3: Merge (automated)
  multiple CSV files -> merge_reviews.py -> single merged CSV
```

---

## Phase 1 - Python Pipeline

Entry point: `main.py`. Runs 4 sequential steps:

```
                          shops.txt
                              |
                  Step 0 (optional, auto-find shops)
                     |                    |
              mode = "users"       mode = "products"
              shop_finder.py    product_shop_finder.py
                     |                    |
                     +-> append to shops.txt <-+
                              |
                  Step 1: shop_crawler.py
                  Fetch shop details via async API
                              |
                     data/shop_detail.csv
                              |
                  Step 2: product_crawler.py
                  Scrape products via Chrome browser
                              |
                      data/pdp_detail.csv
                              |
                  Step 3: review_crawler.py
                  Scrape review samples (1-5 stars) via browser + XHR
                              |
                data/product_review_samples.csv
                + updates star_1..star_5 in pdp_detail.csv
```

### Quick Start

```bash
# 1. Copy and edit environment config
cp .env.example .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the pipeline
python main.py
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SHOPEE_CHROME_PORT` | 9222 | Chrome debugging port |
| `SHOPEE_AUTO_FIND_SHOPS` | 0 | Set to 1 to auto-discover shops from keywords |
| `SHOPEE_SHOP_DISCOVERY_MODE` | users | `users` (search users) or `products` (search product listings) |
| `SHOPEE_KEYWORDS` | _(empty)_ | Pipe-separated keywords. e.g. `ao thun nam\|giay sneaker` |
| `SHOPEE_PRODUCT_LIMIT` | _(empty)_ | Max products to crawl. Empty = unlimited |
| `SHOPEE_REVIEWS_PER_STAR` | 5 | Max review samples per star bucket |
| `SHOPEE_REVIEW_ONLY_PENDING` | 1 | Only crawl products that still need reviews |
| `SHOPEE_REVIEW_SKIP_SAMPLED` | 1 | Skip products already fully sampled |
| `SHOPEE_REVIEW_ITEMIDS` | _(empty)_ | Comma-separated itemids to crawl (subset mode) |
| `SHOPEE_REVIEW_START_INDEX` | 0 | Start from the Nth product in the list |

### Output Files

| File | Content | Key Columns |
|------|---------|-------------|
| `data/shop_detail.csv` | Shop metadata | `shopid` |
| `data/pdp_detail.csv` | Product details + star distribution | `shopid`, `itemid` |
| `data/product_review_samples.csv` | Review samples per star bucket | `code`, `rating_id`, `rating_star` |

### Notes

- Chrome opens automatically. **Log in to Shopee** if not already logged in.
- Solve **CAPTCHA** manually when prompted.
- Pipeline supports **resume**: re-running skips already crawled data.
- Data is saved after each shop/product, so interruptions don't lose progress.

---

## Phase 2 - Chrome Extension

Located in `shopee-review-extension/`. Scrapes reviews from within a real browser session, which avoids most anti-bot detection.

### Installation

```
1. Open Chrome -> navigate to chrome://extensions/
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the shopee-review-extension/ folder
```

### Mode 1: Single Product

```
1. Open a Shopee product page: https://shopee.vn/product/{shopId}/{itemId}
2. Click the extension icon
3. Set "Reviews per star" (default: 5)
4. Click "Start Scraping"
5. Wait 10-30 seconds
6. Click "Download CSV"
```

### Mode 2: Batch from CSV

```
1. Click extension icon
2. Select Mode: "Batch from CSV"
3. Load a CSV file (e.g. data/pdp_detail.csv) - must have columns: shopid, itemid
4. Configure:
   - Start row: which row to begin from (default: 1)
   - Break every: products per batch before taking a break (default: 50)
5. Click "Start Scraping"
```

The extension will automatically:
- Navigate to each product page
- Scrape reviews for stars 1-5
- Take a 2-4 minute break every N products (browses Shopee homepage)
- Auto-download CSV after each batch

### Output Format

Files named: `shopee_reviews_batch_{final|partial}_{timestamp}.csv`

```csv
code,itemid,shopid,rating_star,sample_index,rating_id,author_username,like_count,ctime,t_ctime,comment,product_items,insert_date
```

- `code` = `{shopid}_{itemid}` (product identifier)
- `sample_index` = review order within each star bucket
- `rating_id` = unique review ID (used for deduplication)

---

## Phase 3 - Merge Reviews

`merge_reviews.py` merges multiple CSV files from the extension into a single file.

### Usage

```bash
# Merge all shopee_reviews_*.csv files recursively from current directory
python merge_reviews.py --input-dir . --output merged_reviews.csv

# Merge from a specific directory
python merge_reviews.py --input-dir ./data/review --output ./data/all_reviews.csv

# Custom file pattern
python merge_reviews.py --pattern "shopee_reviews_batch_*.csv" --output merged.csv
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--input-dir` | `.` | Root directory to scan for CSV files (recursive) |
| `--pattern` | `shopee_reviews_*.csv` | Glob pattern to match files |
| `--output` | `merged_reviews.csv` | Output file path |

### What It Does

- **Deduplicates** by `rating_id`
- **Sorts** by `code`, `shopid`, `itemid`, `rating_star`, `sample_index`
- **Fills missing** `code` column as `{shopid}_{itemid}`
- **Normalizes** numeric columns

---

## Recommended Workflow

### Step 1: Prepare shop list

Edit `shops.txt` (one shop per line - username or numeric shopid):

```
coolmate.vn
poloman.vn
12345678
```

Or enable auto-discovery in `.env`:
```
SHOPEE_AUTO_FIND_SHOPS=1
SHOPEE_KEYWORDS=ao thun nam|giay sneaker nam
SHOPEE_SHOP_DISCOVERY_MODE=products
```

### Step 2: Run Python pipeline

```bash
python main.py
```

This produces `data/pdp_detail.csv` with all products.

### Step 3: Scrape reviews with the Extension

1. Install the extension in Chrome
2. Open extension, select "Batch from CSV"
3. Load `data/pdp_detail.csv`
4. Click Start - let it run, save the downloaded CSV files

### Step 4: Merge results

```bash
python merge_reviews.py --input-dir . --output data/all_reviews_merged.csv
```

---

## Project Structure

```
.
├── .env.example                # Environment config template
├── main.py                     # Pipeline entry point
├── shops.txt                   # Input: list of shops
├── requirements.txt            # Python dependencies
├── merge_reviews.py            # Tool to merge review CSVs
├── README.md                   # This file
│
├── config/
│   └── config.py               # Pydantic settings, logging setup
│
├── crawlers/
│   ├── __init__.py
│   ├── csv_store.py            # CSV read/write/upsert utilities
│   ├── shop_finder.py          # Step 0a: find shops via user search
│   ├── product_shop_finder.py  # Step 0b: find shops via product search
│   ├── shop_crawler.py         # Step 1: fetch shop details (async API)
│   ├── product_crawler.py      # Step 2: scrape products (browser)
│   └── review_crawler.py       # Step 3: scrape review samples (browser + XHR)
│
├── utils/
│   ├── runtime.py              # Centralized config (env vars, paths)
│   └── utils.py                # Timer decorator
│
├── shopee-review-extension/    # Chrome Extension for review scraping
│   ├── manifest.json
│   ├── background.js           # Service worker: batch management, downloads
│   ├── popup.html              # Extension popup UI
│   ├── popup.js                # Popup logic + single-product scraping
│   └── content.js              # Content script (floating button on product pages)
│
└── data/                       # Output directory
    ├── shop_detail.csv
    ├── pdp_detail.csv
    └── product_review_samples.csv
```

---

## Troubleshooting

### CAPTCHA appears

- **Python pipeline**: pauses and shows a prompt. Solve the CAPTCHA in Chrome, then press Enter.
- **Extension**: reports "blocked" status. Solve CAPTCHA, refresh the page, restart scraping.

### Redirected to login page

- Log in to Shopee on the Chrome profile being used.
- Wait 1-2 minutes for the session to stabilize.
- Re-run the pipeline or extension.

### API error 90309999 (session rejected)

- Session expired. Refresh shopee.vn in Chrome.
- Log in again if needed.
- The Python crawler automatically falls back to packet listener mode.

### Resuming after interruption

- **Python pipeline**: automatically reads existing data and only crawls what's missing.
- **Extension batch**: set "Start row" to the last completed row + 1.
- **Merge**: always deduplicates by `rating_id`, so re-merging is safe.
