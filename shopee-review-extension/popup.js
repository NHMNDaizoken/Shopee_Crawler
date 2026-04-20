let isScraping = false;
let collectedData = [];
let statusPollTimer = null;

const modeEl = document.getElementById("mode");
const csvFileEl = document.getElementById("csvFile");
const batchStartIndexEl = document.getElementById("batchStartIndex");
const batchSizeEl = document.getElementById("batchSize");
const batchConfigEl = document.getElementById("batchConfig");
const reviewsPerStarEl = document.getElementById("reviewsPerStar");
const startBtnEl = document.getElementById("startBtn");
const stopBtnEl = document.getElementById("stopBtn");
const downloadBtnEl = document.getElementById("downloadBtn");
const starStatsEl = document.getElementById("starStats");
const starStatsTitleEl = document.getElementById("starStatsTitle");

function createEmptyStarBreakdown() {
  return {1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
}

function buildStarBreakdownFromRows(rows) {
  const breakdown = createEmptyStarBreakdown();
  for (const row of Array.isArray(rows) ? rows : []) {
    const star = Number.parseInt(row?.rating_star, 10);
    if (star >= 1 && star <= 5) {
      breakdown[star] += 1;
    }
  }
  return breakdown;
}

function normalizeStarBreakdown(value) {
  const breakdown = createEmptyStarBreakdown();
  for (let star = 1; star <= 5; star += 1) {
    const count = Number.parseInt(value?.[star] ?? value?.[String(star)] ?? 0, 10);
    breakdown[star] = Number.isFinite(count) ? count : 0;
  }
  return breakdown;
}

function renderStarBreakdown(value, title = "Số review đã lấy") {
  const breakdown = normalizeStarBreakdown(value);
  const total = Object.values(breakdown).reduce((sum, count) => sum + count, 0);
  starStatsTitleEl.textContent = title;
  for (let star = 1; star <= 5; star += 1) {
    document.getElementById(`starCount${star}`).textContent = String(breakdown[star]);
  }
  starStatsEl.classList.toggle("visible", total > 0);
}

modeEl.addEventListener("change", () => {
  batchConfigEl.style.display = modeEl.value === "batch" ? "block" : "none";
});

startBtnEl.addEventListener("click", async () => {
  const reviewsPerStar = parseInt(reviewsPerStarEl.value, 10);
  const mode = modeEl.value;

  if (mode === "current") {
    await startCurrentPageScraping(reviewsPerStar);
    return;
  }

  await startBatchScraping(reviewsPerStar);
});

stopBtnEl.addEventListener("click", async () => {
  isScraping = false;
  await chrome.runtime.sendMessage({ action: "STOP_BATCH" });
  showStatus("Stopped by user", "info");
  renderBatchStatus({ active: false });
});

downloadBtnEl.addEventListener("click", () => {
  downloadCSV();
});

function resetPopupState() {
  isScraping = false;
  collectedData = [];
  downloadBtnEl.style.display = "none";
  renderBatchStatus({ active: false });
  showStatus("", "info");
  updateProgress("");
  renderStarBreakdown(createEmptyStarBreakdown());
}

async function startCurrentPageScraping(reviewsPerStar) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url || !tab.url.includes("shopee.vn")) {
      showStatus("❌ Please open a Shopee product page first!", "error");
      return;
    }

    isScraping = true;
    renderBatchStatus({ active: true });
    showStatus("🔄 Starting scraper...", "info");

    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: scrapeReviews,
      args: [reviewsPerStar],
    });

    const payload = results?.[0]?.result;
    const rows = Array.isArray(payload) ? payload : payload?.rows;
    if (Array.isArray(rows)) {
      collectedData = rows;
      const starBreakdown = Array.isArray(payload) ? buildStarBreakdownFromRows(rows) : payload?.starBreakdown;
      renderStarBreakdown(starBreakdown, "Sản phẩm hiện tại");

      if (collectedData.length > 0) {
        showStatus(`✅ Collected ${collectedData.length} reviews!`, "success");
        downloadBtnEl.style.display = "block";
      } else {
        showStatus("⚠️ No reviews found (empty result)", "error");
      }
    } else {
      showStatus("❌ Script returned no data", "error");
    }
  } catch (error) {
    showStatus(`❌ Error: ${error.message}`, "error");
  } finally {
    isScraping = false;
    renderBatchStatus({ active: false });
  }
}

async function startBatchScraping(reviewsPerStar) {
  const file = csvFileEl.files?.[0];
  if (!file) {
    showStatus("❌ Chọn file CSV trước khi chạy batch", "error");
    return;
  }

  try {
    resetPopupState();
    const text = await file.text();
    const products = parseProductsCsv(text);
    if (products.length === 0) {
      showStatus("❌ CSV không có dòng hợp lệ", "error");
      return;
    }

    const startIndex = Math.max(parseInt(batchStartIndexEl.value || "1", 10), 1);
    const batchSize = Math.max(parseInt(batchSizeEl.value || "50", 10), 1);
    const remainingProducts = products.slice(startIndex - 1);
    if (remainingProducts.length === 0) {
      showStatus("❌ Không còn sản phẩm nào từ start row này", "error");
      return;
    }

    await chrome.runtime.sendMessage({
      action: "START_BATCH",
      products: remainingProducts,
      reviewsPerStar,
      sourceName: file.name,
      startIndex,
      batchSize,
    });

    showStatus(
      `🔄 Batch started: từ row ${startIndex}, tổng ${remainingProducts.length} sản phẩm, nghỉ mỗi ${batchSize} sản phẩm`,
      "info",
    );
    renderBatchStatus({ active: true });
    startPollingStatus();
  } catch (error) {
    showStatus(`❌ Batch error: ${error.message}`, "error");
  }
}

function renderBatchStatus(status) {
  const active = Boolean(status?.active);
  stopBtnEl.style.display = active ? "block" : "none";
  startBtnEl.style.display = active ? "none" : "block";
}

function showStatus(message, type) {
  const statusEl = document.getElementById("status");
  statusEl.textContent = message;
  statusEl.className = `status ${type}`;
}

function updateProgress(message) {
  document.getElementById("progress").textContent = message || "";
}

function downloadCSV() {
  if (collectedData.length === 0) {
    showStatus("No data to download", "error");
    return;
  }

  const headers = [
    "code",
    "itemid",
    "shopid",
    "rating_star",
    "sample_index",
    "rating_id",
    "author_username",
    "like_count",
    "ctime",
    "t_ctime",
    "comment",
    "product_items",
    "insert_date",
  ];
  const csv = [
    "\uFEFF" + headers.join(","),
    ...collectedData.map((row) =>
      headers.map((header) => {
        const value = String(row[header] ?? "");
        return `"${value.replace(/"/g, "\"\"")}"`;
      }).join(","),
    ),
  ].join("\n");

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, -5);
  const filename = `shopee_reviews_${timestamp}.csv`;

  chrome.runtime.sendMessage(
    {
      action: "DOWNLOAD_CSV",
      data: csv,
      filename,
    },
    (response) => {
      if (response && response.success) {
        showStatus("✅ Download started!", "success");
      }
    },
  );
}

function startPollingStatus() {
  if (statusPollTimer) {
    window.clearInterval(statusPollTimer);
  }

  const poll = async () => {
    try {
      const status = await chrome.runtime.sendMessage({ action: "GET_BATCH_STATUS" });
      if (!status) {
        return;
      }

      renderBatchStatus(status);
      renderStarBreakdown(status.starBreakdown, "Tổng review đã cào");
      if (status.active) {
        updateProgress(
          `Progress: ${status.currentIndex}/${status.totalProducts} | rows=${status.totalRows} | skipped=${status.skippedProducts || 0} | failed=${status.failedProducts || 0} | source row ${status.startIndex + status.currentIndex}`,
        );
      } else {
        updateProgress(
          status.totalProducts
            ? `Done: ${status.currentIndex}/${status.totalProducts} | rows=${status.totalRows} | skipped=${status.skippedProducts || 0} | failed=${status.failedProducts || 0}`
            : "",
        );
      }

      if (status.lastError) {
        showStatus(`⚠️ ${status.lastError}`, "error");
      } else if (status.onBreak) {
        const remainingMs = Math.max((status.breakUntil || 0) - Date.now(), 0);
        const remainingSec = Math.ceil(remainingMs / 1000);
        showStatus(`🕒 Nghỉ giữa batch, sẽ chạy tiếp sau khoảng ${remainingSec}s`, "info");
      } else if (status.active) {
        showStatus(`🔄 ${status.currentProductName || "Running batch..."}`, "info");
      } else if (status.completedAt) {
        showStatus(`✅ Batch done: ${status.totalRows} rows`, "success");
        if (status.downloadReady) {
          downloadBtnEl.style.display = "block";
          collectedData = status.rows || [];
        }
      } else {
        resetPopupState();
      }
    } catch (error) {
      console.error("status poll error", error);
    }
  };

  poll();
  statusPollTimer = window.setInterval(poll, 1000);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];

    if (inQuotes) {
      if (char === "\"") {
        if (text[index + 1] === "\"") {
          field += "\"";
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === "\"") {
      inQuotes = true;
      continue;
    }

    if (char === ",") {
      row.push(field);
      field = "";
      continue;
    }

    if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") {
        index += 1;
      }
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      continue;
    }

    field += char;
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  return rows;
}

function parseProductsCsv(text) {
  const rows = parseCsv(text.replace(/^\uFEFF/, ""));
  if (rows.length < 2) {
    return [];
  }

  const headers = rows[0].map((header) => String(header || "").trim());
  const headerIndex = Object.fromEntries(headers.map((header, index) => [header, index]));
  if (!("shopid" in headerIndex) || !("itemid" in headerIndex)) {
    throw new Error("CSV cần có cột shopid,itemid");
  }

  const seenKeys = new Set();
  const products = [];
  for (let rowIndex = 1; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex];
    const shopId = String(row[headerIndex.shopid] ?? "").trim().replace(/\.0$/, "");
    const itemId = String(row[headerIndex.itemid] ?? "").trim().replace(/\.0$/, "");
    const name = "name" in headerIndex ? String(row[headerIndex.name] ?? "").trim() : "";
    const cmtCountRaw = "cmt_count" in headerIndex ? String(row[headerIndex.cmt_count] ?? "").trim() : "";
    const cmtCount = cmtCountRaw ? Number.parseInt(cmtCountRaw.replace(/[^\d]/g, ""), 10) : null;
    if (!shopId || !itemId) {
      continue;
    }
    if (Number.isInteger(cmtCount) && cmtCount < 5) {
      continue;
    }
    const key = `${shopId}:${itemId}`;
    if (seenKeys.has(key)) {
      continue;
    }
    seenKeys.add(key);
    products.push({
      shopId,
      itemId,
      name: name || key,
      url: `https://shopee.vn/product/${shopId}/${itemId}`,
    });
  }

  return products;
}

resetPopupState();
startPollingStatus();

function scrapeReviews(reviewsPerStar) {
  return new Promise(async (resolve) => {
    const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
    const makeEmptyStarBreakdown = () => ({1: 0, 2: 0, 3: 0, 4: 0, 5: 0});
    const reviews = [];
    const seenIds = new Set();
    const starBreakdown = makeEmptyStarBreakdown();
    const pokePage = () => {
      try {
        window.focus();
        document.documentElement?.focus?.({preventScroll: true});
        document.body?.focus?.({preventScroll: true});
      } catch (error) {
        // Ignore focus failures inside page context.
      }
      try {
        window.dispatchEvent(new Event("focus"));
        document.dispatchEvent(new Event("visibilitychange"));
        document.body?.dispatchEvent(new MouseEvent("mousemove", {bubbles: true, clientX: 120, clientY: 180}));
        document.body?.dispatchEvent(new WheelEvent("wheel", {bubbles: true, deltaY: 180}));
      } catch (error) {
        // Synthetic events may still help page listeners even if not trusted.
      }
    };
    const warmUpProductPage = async () => {
      window.scrollTo({top: 0, behavior: "instant"});
      pokePage();
      await sleep(180);

      const downSteps = [260, 420, 640, 860];
      for (const step of downSteps) {
        window.scrollBy({top: step, behavior: "instant"});
        pokePage();
        await sleep(160);
      }

      const upSteps = [-220, -180];
      for (const step of upSteps) {
        window.scrollBy({top: step, behavior: "instant"});
        pokePage();
        await sleep(140);
      }
    };
    const findReviewRoot = () =>
      document.querySelector(".product-ratings") ??
      Array.from(document.querySelectorAll("div, section")).find((element) =>
        /ĐÁNH GIÁ SẢN PHẨM|đánh giá|reviews?/i.test(element.textContent ?? ""),
      ) ??
      null;
    const tryActivateReviewSection = () => {
      const reviewRoot = findReviewRoot();
      if (!reviewRoot) {
        return false;
      }
      reviewRoot.scrollIntoView({behavior: "instant", block: "start"});
      const clickable = reviewRoot.querySelector("button, [role='tab'], [role='button'], .product-rating-overview__filters");
      clickable?.click?.();
      return true;
    };
    const reachReviewSection = async () => {
      for (let step = 0; step < 12; step += 1) {
        pokePage();
        const state = (() => {
          const reviewRoot = findReviewRoot();
          const reviewCount = document.querySelectorAll(
            ".shopee-product-comment-list > div[data-cmtid], .shopee-product-comment-list > div.q2b7Oq",
          ).length;

          if (reviewRoot) {
            reviewRoot.scrollIntoView({behavior: "instant", block: "start"});
            tryActivateReviewSection();
          } else {
            window.scrollBy({top: Math.max(window.innerHeight * 0.55, 420), behavior: "instant"});
          }

          return {
            hasReviewRoot: Boolean(reviewRoot),
            reviewCount,
          };
        })();

        if (state.hasReviewRoot || state.reviewCount > 0) {
          return true;
        }
        await sleep(450);
      }
      return false;
    };
    const code = (() => {
      const urlMatch = window.location.pathname.match(/\/product\/(\d+)\/(\d+)/);
      if (!urlMatch) {
        return "";
      }
      const [, shopId, itemId] = urlMatch;
      return `${shopId}_${itemId}`;
    })();

    try {
      const urlMatch = window.location.pathname.match(/\/product\/(\d+)\/(\d+)/);
      if (!urlMatch) {
        resolve({rows: [], starBreakdown});
        return;
      }
      const [, shopId, itemId] = urlMatch;

      await warmUpProductPage();
      await reachReviewSection();

      let fetchUtils = null;
      for (let i = 0; i < 30; i += 1) {
        pokePage();
        if (i % 3 === 0) {
          tryActivateReviewSection();
        }
        fetchUtils = window.PlatformApi?.FetchUtils;
        if (fetchUtils && fetchUtils.get) {
          break;
        }
        window.scrollBy({top: i % 2 === 0 ? 180 : -60, behavior: "instant"});
        await sleep(250);
      }

      if (!fetchUtils || !fetchUtils.get) {
        resolve({rows: [], starBreakdown});
        return;
      }

      const clickStarFilter = async (star) => {
        const starPattern = new RegExp(`^\\s*${star}\\s*sao\\b`, "i");
        const filterElements = Array.from(document.querySelectorAll(".product-rating-overview__filter, button, [role='tab'], [role='button']"));
        const target = filterElements.find((element) => starPattern.test((element.textContent || "").trim()));
        target?.click?.();
      };

      let ratingCount = null;
      try {
        const summaryParams = new URLSearchParams({
          itemid: itemId,
          shopid: shopId,
          filter: "0",
          limit: "1",
          offset: "0",
          type: "0",
        });
        const summaryResponse = await fetchUtils.get(`/api/v2/item/get_ratings?${summaryParams}`);
        const summaryCounts = summaryResponse?.data?.item_rating_summary?.rating_count;
        if (Array.isArray(summaryCounts)) {
          ratingCount = summaryCounts;
        }
      } catch (error) {
        ratingCount = null;
      }

      // FIX: thay vì loop 5 lần filter=N (Shopee trả mismatch → break sớm),
      // dùng 1 loop filter=0 rồi bucket theo rating.rating_star THẰT.
      const collectedPerStar = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
      const sampleIndexPerStar = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
      let offset = 0;
      let consecutiveEmpty = 0;
      const MAX_EMPTY = 3;
      const MAX_OFFSET = 5000;
      const allFull = () => [1, 2, 3, 4, 5].every((s) => collectedPerStar[s] >= reviewsPerStar);

      while (!allFull() && offset < MAX_OFFSET) {
        try {
          const params = new URLSearchParams({
            itemid: itemId,
            shopid: shopId,
            filter: "0",
            limit: "20",
            offset: String(offset),
            type: "0",
          });

          const response = await fetchUtils.get(`/api/v2/item/get_ratings?${params}`);
          if (response?.error !== 0 || !response?.data) break;

          const ratings = response.data.ratings || [];
          if (ratings.length === 0) {
            consecutiveEmpty += 1;
            if (consecutiveEmpty >= MAX_EMPTY) break;
            offset += 20;
            await sleep(800);
            continue;
          }
          consecutiveEmpty = 0;

          for (const rating of ratings) {
            const actualStar = Number(rating.rating_star);
            if (!(actualStar >= 1 && actualStar <= 5)) continue;
            if (collectedPerStar[actualStar] >= reviewsPerStar) continue;

            const ratingId = String(rating.rating_id || rating.ratingsid || rating.cmtid || "");
            if (!ratingId || seenIds.has(ratingId)) continue;

            const comment = (rating.comment || "").trim();
            if (!comment) continue;

            seenIds.add(ratingId);
            collectedPerStar[actualStar] += 1;
            sampleIndexPerStar[actualStar] += 1;
            starBreakdown[actualStar] += 1;

            const productItems = (rating.product_items || [])
              .map((item) => item.model_name || "")
              .filter(Boolean)
              .join(", ");
            const ctime = rating.ctime || 0;
            const tCtime = ctime ? new Date(ctime * 1000).toISOString().replace("T", " ").substring(0, 19) : "";

            reviews.push({
              code,
              itemid: itemId,
              shopid: shopId,
              rating_star: actualStar,
              sample_index: sampleIndexPerStar[actualStar],
              rating_id: ratingId,
              author_username: rating.author_username || "",
              like_count: rating.like_count || 0,
              ctime,
              t_ctime: tCtime,
              comment,
              product_items: productItems,
              insert_date: new Date().toISOString().replace("T", " ").substring(0, 19),
            });
          }

          offset += ratings.length;
          await sleep(300);
        } catch (error) {
          break;
        }
      }

      // PHASE B: star nào vẫn thiếu → fetch riêng filter=N (validate actualStar).
      for (const star of [1, 2, 3, 4, 5]) {
        if (collectedPerStar[star] >= reviewsPerStar) continue;
        // Skip star = 0 review (theo summary)
        if (Array.isArray(ratingCount) && Number(ratingCount[star] || 0) === 0) continue;

        let starOffset = 0;
        let starEmpty = 0;
        const STAR_MAX_OFFSET = 1500;
        const STAR_MAX_EMPTY = 5;

        while (collectedPerStar[star] < reviewsPerStar && starOffset < STAR_MAX_OFFSET) {
          try {
            const params = new URLSearchParams({
              itemid: itemId,
              shopid: shopId,
              filter: String(star),
              limit: "20",
              offset: String(starOffset),
              type: "0",
            });

            const response = await fetchUtils.get(`/api/v2/item/get_ratings?${params}`);
            if (response?.error !== 0 || !response?.data) break;

            const ratings = response.data.ratings || [];
            if (ratings.length === 0) {
              starEmpty += 1;
              if (starEmpty >= STAR_MAX_EMPTY) break;
              starOffset += 20;
              await sleep(800);
              continue;
            }
            starEmpty = 0;

            for (const rating of ratings) {
              const actualStar = Number(rating.rating_star);
              if (actualStar !== star) continue;
              if (collectedPerStar[star] >= reviewsPerStar) break;

              const ratingId = String(rating.rating_id || rating.ratingsid || rating.cmtid || "");
              if (!ratingId || seenIds.has(ratingId)) continue;

              const comment = (rating.comment || "").trim();
              if (!comment) continue;

              seenIds.add(ratingId);
              collectedPerStar[star] += 1;
              sampleIndexPerStar[star] += 1;
              starBreakdown[star] += 1;

              const productItems = (rating.product_items || [])
                .map((item) => item.model_name || "")
                .filter(Boolean)
                .join(", ");
              const ctime = rating.ctime || 0;
              const tCtime = ctime ? new Date(ctime * 1000).toISOString().replace("T", " ").substring(0, 19) : "";

              reviews.push({
                code,
                itemid: itemId,
                shopid: shopId,
                rating_star: star,
                sample_index: sampleIndexPerStar[star],
                rating_id: ratingId,
                author_username: rating.author_username || "",
                like_count: rating.like_count || 0,
                ctime,
                t_ctime: tCtime,
                comment,
                product_items: productItems,
                insert_date: new Date().toISOString().replace("T", " ").substring(0, 19),
              });
            }

            starOffset += ratings.length;
            await sleep(300);
          } catch (error) {
            break;
          }
        }
      }

      resolve({rows: reviews, starBreakdown});
    } catch (error) {
      resolve({rows: [], starBreakdown});
    }
  });
}
