const STORAGE_KEY = "batchState";
const MAX_CONSECUTIVE_EMPTY_OR_FAILED = 3;
const BREAK_EVERY_PRODUCTS = 20;
const BREAK_ALARM_NAME = "batchHumanBreak";
const BREAK_MIN_MS = 2 * 60 * 1000;
const BREAK_MAX_MS = 4 * 60 * 1000;

function createEmptyStarBreakdown() {
  return {1: 0, 2: 0, 3: 0, 4: 0, 5: 0};
}

function mergeStarBreakdown(base = createEmptyStarBreakdown(), delta = createEmptyStarBreakdown()) {
  const merged = createEmptyStarBreakdown();
  for (let star = 1; star <= 5; star += 1) {
    const left = Number.parseInt(base?.[star] ?? base?.[String(star)] ?? 0, 10);
    const right = Number.parseInt(delta?.[star] ?? delta?.[String(star)] ?? 0, 10);
    merged[star] = (Number.isFinite(left) ? left : 0) + (Number.isFinite(right) ? right : 0);
  }
  return merged;
}

function createEmptyBatchState() {
  return {
    active: false,
    paused: false,
    startIndex: 1,
    currentIndex: 0,
    totalProducts: 0,
    currentProductName: "",
    currentTabId: null,
    reviewsPerStar: 5,
    breakEveryProducts: BREAK_EVERY_PRODUCTS,
    sourceName: "",
    products: [],
    rows: [],
    totalRows: 0,
    skippedProducts: 0,
    failedProducts: 0,
    consecutiveEmptyOrFailed: 0,
    processedSinceBreak: 0,
    onBreak: false,
    breakUntil: 0,
    lastError: "",
    completedAt: "",
    downloadReady: false,
    starBreakdown: createEmptyStarBreakdown(),
  };
}

let batchState = createEmptyBatchState();
let batchWorkerBusy = false;
let batchStateReady = loadBatchState();

chrome.runtime.onInstalled.addListener(async () => {
  await resetBatchState();
  batchStateReady = Promise.resolve();
});

chrome.runtime.onStartup?.addListener(async () => {
  await resetBatchState();
  batchStateReady = Promise.resolve();
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== BREAK_ALARM_NAME) {
    return;
  }

  await batchStateReady;
  if (!batchState.active || !batchState.onBreak) {
    return;
  }

  batchState.onBreak = false;
  batchState.breakUntil = 0;
  batchState.lastError = "";
  await saveBatchState();
  await gotoNextProduct();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "DOWNLOAD_CSV") {
    const url = `data:text/csv;charset=utf-8,${encodeURIComponent(message.data || "")}`;

    chrome.downloads.download(
      {
        url,
        filename: message.filename || "shopee_reviews.csv",
        saveAs: true,
      },
      (downloadId) => {
        sendResponse({success: true, downloadId});
      },
    );

    return true;
  }

  if (message.action === "START_BATCH") {
    batchStateReady
      .then(() => startBatch(message))
      .then(() => sendResponse({success: true}))
      .catch((error) => sendResponse({success: false, error: error.message}));
    return true;
  }

  if (message.action === "STOP_BATCH") {
    batchStateReady
      .then(() => stopBatch("Stopped by user"))
      .then(() => sendResponse({success: true}))
      .catch((error) => sendResponse({success: false, error: error.message}));
    return true;
  }

  if (message.action === "GET_BATCH_STATUS") {
    batchStateReady
      .then(async () => {
        if (batchState.active || batchState.paused) {
          await kickBatchIfPossible();
        } else if (hasResidualBatchState()) {
          await resetBatchState();
        }

        sendResponse({
          active: batchState.active,
          paused: batchState.paused,
          startIndex: batchState.startIndex,
          currentIndex: batchState.currentIndex,
          totalProducts: batchState.totalProducts,
          currentProductName: batchState.currentProductName,
          totalRows: batchState.totalRows,
          skippedProducts: batchState.skippedProducts,
          failedProducts: batchState.failedProducts,
          consecutiveEmptyOrFailed: batchState.consecutiveEmptyOrFailed,
          processedSinceBreak: batchState.processedSinceBreak,
          onBreak: batchState.onBreak,
          breakUntil: batchState.breakUntil,
          lastError: batchState.lastError,
          completedAt: batchState.completedAt,
          downloadReady: batchState.downloadReady,
          starBreakdown: batchState.starBreakdown,
          rows: batchState.downloadReady ? batchState.rows : [],
        });
      })
      .catch((error) => sendResponse({success: false, error: error.message}));
    return true;
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  await batchStateReady;
  if (!batchState.active || batchState.paused) {
    return;
  }
  if (batchState.onBreak) {
    return;
  }
  if (batchWorkerBusy) {
    return;
  }
  if (tabId !== batchState.currentTabId || changeInfo.status !== "complete") {
    return;
  }

  const target = batchState.products[batchState.currentIndex];
  if (!target || tab.url !== target.url) {
    return;
  }

  try {
    batchWorkerBusy = true;
    batchState.currentProductName = target.name || `${target.shopId}:${target.itemId}`;
    await saveBatchState();
    await processBatchTarget(tabId, target);
  } catch (error) {
    batchState.paused = true;
    batchState.lastError = error instanceof Error ? error.message : String(error);
    await saveBatchState();
  } finally {
    batchWorkerBusy = false;
  }
});

async function loadBatchState() {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  if (stored && stored[STORAGE_KEY]) {
    batchState = {...batchState, ...stored[STORAGE_KEY]};
  }
}

function hasResidualBatchState() {
  return Boolean(
    batchState.currentIndex ||
      batchState.totalProducts ||
      batchState.currentProductName ||
      batchState.currentTabId !== null ||
      batchState.products.length ||
      batchState.rows.length ||
      batchState.totalRows ||
      batchState.lastError ||
      batchState.completedAt ||
      batchState.downloadReady,
  );
}

async function resetBatchState() {
  batchState = createEmptyBatchState();
  batchWorkerBusy = false;
  await chrome.alarms.clear(BREAK_ALARM_NAME);
  await chrome.storage.local.remove(STORAGE_KEY);
}

async function saveBatchState() {
  await chrome.storage.local.set({[STORAGE_KEY]: batchState});
}

async function startBatch(message) {
  const products = Array.isArray(message.products) ? message.products : [];
  if (products.length === 0) {
    throw new Error("Batch requires at least one product.");
  }

  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab || typeof tab.id !== "number") {
    throw new Error("Cannot detect current tab.");
  }

  batchState = {
    ...createEmptyBatchState(),
    active: true,
    startIndex: Math.max(Number.parseInt(message.startIndex, 10) || 1, 1),
    currentTabId: tab.id,
    reviewsPerStar: Number.parseInt(message.reviewsPerStar, 10) || 5,
    breakEveryProducts: Math.max(Number.parseInt(message.batchSize, 10) || BREAK_EVERY_PRODUCTS, 1),
    sourceName: message.sourceName || "",
    products,
    totalProducts: products.length,
  };
  await saveBatchState();
  await gotoNextProduct();
}

async function stopBatch(reason = "") {
  if (batchState.rows.length > 0) {
    await downloadBatchCsv({partial: true, saveAs: false});
  }
  await resetBatchState();
}

async function gotoNextProduct() {
  if (!batchState.active) {
    return;
  }
  if (batchState.onBreak) {
    return;
  }

  if (batchState.currentIndex >= batchState.totalProducts) {
    await downloadBatchCsv({partial: false, saveAs: true});
    await resetBatchState();
    return;
  }

  const target = batchState.products[batchState.currentIndex];
  batchState.currentProductName = target.name || `${target.shopId}:${target.itemId}`;
  await saveBatchState();

  await chrome.tabs.update(batchState.currentTabId, {url: target.url, active: true});
}

async function kickBatchIfPossible() {
  if (!batchState.active || batchState.paused) {
    return;
  }
  if (batchState.onBreak) {
    if (batchState.breakUntil && Date.now() >= batchState.breakUntil) {
      batchState.onBreak = false;
      batchState.breakUntil = 0;
      batchState.lastError = "";
      await saveBatchState();
      await gotoNextProduct();
    }
    return;
  }
  if (batchWorkerBusy) {
    return;
  }

  if (!Number.isInteger(batchState.currentTabId)) {
    batchState.paused = true;
    batchState.lastError = "Không còn tab chạy batch. Mở lại batch từ popup.";
    await saveBatchState();
    return;
  }

  if (batchState.currentIndex >= batchState.totalProducts) {
    await gotoNextProduct();
    return;
  }

  let tab;
  try {
    tab = await chrome.tabs.get(batchState.currentTabId);
  } catch (error) {
    batchState.paused = true;
    batchState.lastError = "Tab batch đã bị đóng. Mở lại batch từ popup.";
    await saveBatchState();
    return;
  }

  const target = batchState.products[batchState.currentIndex];
  if (!target) {
    batchState.paused = true;
    batchState.lastError = "Không tìm thấy sản phẩm hiện tại trong queue.";
    await saveBatchState();
    return;
  }

  const currentUrl = String(tab.url || "");
  if (currentUrl !== target.url) {
    await chrome.tabs.update(batchState.currentTabId, {url: target.url, active: true});
    return;
  }

  if (tab.status === "complete") {
    try {
      batchWorkerBusy = true;
      batchState.currentProductName = target.name || `${target.shopId}:${target.itemId}`;
      await saveBatchState();
      await processBatchTarget(batchState.currentTabId, target);
    } catch (error) {
      batchState.paused = true;
      batchState.lastError = error instanceof Error ? error.message : String(error);
      await saveBatchState();
    } finally {
      batchWorkerBusy = false;
    }
  }
}

async function processBatchTarget(tabId, target) {
  const scrapeResult = await scrapeProductTab(tabId, batchState.reviewsPerStar);

  if (scrapeResult.status === "ok") {
    batchState.rows.push(...scrapeResult.rows);
    batchState.totalRows += scrapeResult.rows.length;
    batchState.starBreakdown = mergeStarBreakdown(batchState.starBreakdown, scrapeResult.starBreakdown);
    batchState.consecutiveEmptyOrFailed = 0;
    batchState.processedSinceBreak += 1;
    batchState.lastError = "";
    batchState.currentIndex += 1;
    await saveBatchState();
    if (await maybeStartHumanBreak()) {
      return;
    }
    await gotoNextProduct();
    return;
  }

  if (scrapeResult.status === "no_reviews") {
    batchState.skippedProducts += 1;
    batchState.consecutiveEmptyOrFailed = 0;
    batchState.processedSinceBreak += 1;
    batchState.lastError = "";
    batchState.currentIndex += 1;
    await saveBatchState();
    if (await maybeStartHumanBreak()) {
      return;
    }
    await gotoNextProduct();
    return;
  }

  batchState.failedProducts += 1;
  batchState.consecutiveEmptyOrFailed += 1;
  batchState.processedSinceBreak += 1;
  batchState.currentIndex += 1;
  batchState.lastError =
    scrapeResult.message ||
    `Không lấy được review cho ${target.name || `${target.shopId}:${target.itemId}`}.`;
  await saveBatchState();

  if (batchState.consecutiveEmptyOrFailed >= MAX_CONSECUTIVE_EMPTY_OR_FAILED) {
    await downloadBatchCsv({partial: true, saveAs: false, resetRows: true});
    await resetBatchState();
    return;
  }

  if (await maybeStartHumanBreak()) {
    return;
  }
  await gotoNextProduct();
}

async function maybeStartHumanBreak() {
  if (!batchState.active || batchState.onBreak) {
    return false;
  }
  if (batchState.processedSinceBreak < (batchState.breakEveryProducts || BREAK_EVERY_PRODUCTS)) {
    return false;
  }

  const breakDurationMs =
    BREAK_MIN_MS + Math.floor(Math.random() * (BREAK_MAX_MS - BREAK_MIN_MS + 1));
  batchState.onBreak = true;
  batchState.breakUntil = Date.now() + breakDurationMs;
  batchState.processedSinceBreak = 0;
  batchState.currentProductName = "Taking a short browsing break...";
  batchState.lastError = "";
  await saveBatchState();

  if (batchState.rows.length > 0) {
    await downloadBatchCsv({partial: true, saveAs: false, resetRows: true});
  }
  await chrome.alarms.create(BREAK_ALARM_NAME, {when: batchState.breakUntil});
  await browseShopeeHomepage(batchState.currentTabId, breakDurationMs);
  return true;
}

async function browseShopeeHomepage(tabId, breakDurationMs) {
  if (!Number.isInteger(tabId)) {
    return;
  }

  await chrome.tabs.update(tabId, {url: "https://shopee.vn/", active: true});
  try {
    await chrome.scripting.executeScript({
      target: {tabId},
      world: "MAIN",
      func: async (durationMs) => {
        const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
        const steps = [220, 380, 540, -180, 260, -120, 460];
        const endAt = Date.now() + Math.min(durationMs, 45000);

        const poke = () => {
          try {
            window.focus();
            document.documentElement?.focus?.({preventScroll: true});
            document.body?.dispatchEvent(new MouseEvent("mousemove", {bubbles: true, clientX: 140, clientY: 220}));
            document.body?.dispatchEvent(new WheelEvent("wheel", {bubbles: true, deltaY: 160}));
          } catch (error) {
            // Ignore page-context interaction failures.
          }
        };

        await sleep(1200);
        window.scrollTo({top: 0, behavior: "instant"});
        while (Date.now() < endAt) {
          for (const step of steps) {
            window.scrollBy({top: step, behavior: "instant"});
            poke();
            await sleep(500 + Math.floor(Math.random() * 700));
            if (Date.now() >= endAt) {
              break;
            }
          }
        }
        window.scrollTo({top: 0, behavior: "instant"});
      },
      args: [breakDurationMs],
    });
  } catch (error) {
    console.warn("browseShopeeHomepage error", error);
  }
}

async function scrapeProductTab(tabId, reviewsPerStar) {
  const results = await chrome.scripting.executeScript({
    target: {tabId},
    world: "MAIN",
    func: scrapeReviews,
    args: [reviewsPerStar],
  });

  if (!results || !results[0]) {
    return {
      status: "error",
      rows: [],
      totalReviewCount: null,
      message: "Script không trả dữ liệu.",
    };
  }
  return results[0].result || {
    status: "error",
    rows: [],
    totalReviewCount: null,
    message: "Script không trả dữ liệu.",
  };
}

function buildBatchCsvText(rows) {
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
  return [
    "\uFEFF" + headers.join(","),
    ...rows.map((row) =>
      headers.map((header) => {
        const value = String(row[header] ?? "");
        return `"${value.replace(/"/g, "\"\"")}"`;
      }).join(","),
    ),
  ].join("\n");
}

async function downloadBatchCsv(options = {}) {
  const {partial = false, saveAs = true, resetRows = false} = options;
  const rows = Array.isArray(batchState.rows) ? batchState.rows : [];
  if (rows.length === 0) {
    return;
  }

  const csv = buildBatchCsvText(rows);

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, -5);
  const suffix = partial ? "partial" : "final";
  const filename = `shopee_reviews_batch_${suffix}_${timestamp}.csv`;
  const url = `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  await chrome.downloads.download({
    url,
    filename,
    saveAs,
  });
  if (resetRows) {
    batchState.rows = [];
    await saveBatchState();
  }
}

function scrapeReviews(reviewsPerStar) {
  return new Promise(async (resolve) => {
    const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
    const makeEmptyStarBreakdown = () => ({1: 0, 2: 0, 3: 0, 4: 0, 5: 0});
    const reviews = [];
    const seenIds = new Set();
    const starBreakdown = makeEmptyStarBreakdown();
    const finish = (status, rows = [], totalReviewCount = null, message = "") => {
      resolve({
        status,
        rows,
        starBreakdown,
        totalReviewCount,
        message,
      });
    };
    const parseCountFromText = (text) => {
      const match = String(text || "")
        .replace(/\s+/g, " ")
        .match(/(\d[\d.,]*)\s*(đánh giá|reviews?)/i);
      if (!match) {
        return null;
      }
      const digits = match[1].replace(/[^\d]/g, "");
      return digits ? Number.parseInt(digits, 10) : null;
    };
    const readDomReviewCount = () => {
      const candidates = [
        ...document.querySelectorAll(
          ".product-rating-overview, .product-ratings, .product-rating-overview__briefing, [class*='rating']",
        ),
      ];
      for (const element of candidates) {
        const count = parseCountFromText(element.textContent);
        if (Number.isInteger(count)) {
          return count;
        }
      }
      return parseCountFromText(document.body?.innerText ?? "");
    };
    const extractTotalReviewCount = (responseData) => {
      const summary = responseData?.item_rating_summary ?? responseData?.rating_summary ?? {};
      const directCandidates = [
        summary.rating_total,
        summary.review_count,
        summary.total_count,
        summary.total,
        summary.rcount,
        responseData?.item_rating_summary?.rating_count,
      ];
      for (const candidate of directCandidates) {
        if (typeof candidate === "number" && Number.isFinite(candidate)) {
          return candidate;
        }
      }
      const domCount = readDomReviewCount();
      return Number.isInteger(domCount) ? domCount : null;
    };
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
    const htmlText = (document.body?.innerText ?? "").toLowerCase();
    if (
      htmlText.includes("trang không khả dụng") ||
      htmlText.includes("vui lòng đăng nhập lại") ||
      window.location.href.includes("/buyer/login") ||
      window.location.href.includes("/verify/")
    ) {
      finish("blocked", [], null, "Shopee đang bắt login/captcha hoặc chặn truy cập.");
      return;
    }

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
        finish("error", [], null, "Không nhận diện được shopid/itemid từ URL.");
        return;
      }
      const [, shopId, itemId] = urlMatch;

      await warmUpProductPage();
      await reachReviewSection();
      const domReviewCount = readDomReviewCount();

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
        const bodyText = (document.body?.innerText ?? "").toLowerCase();
        if (bodyText.includes("trang không khả dụng") || bodyText.includes("vui lòng đăng nhập lại")) {
          finish("blocked", [], null, "Shopee đang bắt login/captcha hoặc chặn truy cập.");
          return;
        }
        window.scrollBy({top: i % 2 === 0 ? 180 : -60, behavior: "instant"});
        await sleep(250);
      }

      if (!fetchUtils || !fetchUtils.get) {
        if (domReviewCount === 0) {
          finish("no_reviews", [], 0, "");
          return;
        }
        finish("error", [], domReviewCount, "Không thấy API review nội bộ xuất hiện.");
        return;
      }

      let totalReviewCount = Number.isInteger(domReviewCount) ? domReviewCount : null;
      for (const star of [5, 1, 2, 3, 4]) {
        let collected = 0;
        let offset = 0;

        while (collected < reviewsPerStar) {
          try {
            const params = new URLSearchParams({
              itemid: itemId,
              shopid: shopId,
              filter: String(star),
              limit: "20",
              offset: String(offset),
              type: "0",
            });

            const response = await fetchUtils.get(`/api/v2/item/get_ratings?${params}`);
            if (response.error !== 0 || !response.data) {
              break;
            }

            const currentTotalReviewCount = extractTotalReviewCount(response.data);
            if (Number.isInteger(currentTotalReviewCount)) {
              totalReviewCount = currentTotalReviewCount;
            }

            const ratings = response.data.ratings || [];
            if (ratings.length === 0) {
              break;
            }

            for (const rating of ratings) {
              if (collected >= reviewsPerStar) {
                break;
              }

              const ratingId = String(rating.rating_id || rating.ratingsid || rating.cmtid || "");
              if (!ratingId || seenIds.has(ratingId)) {
                continue;
              }

              const comment = (rating.comment || "").trim();
              if (!comment) {
                continue;
              }

               seenIds.add(ratingId);
               collected += 1;
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
                sample_index: collected,
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

        await sleep(600);
      }

      if (reviews.length > 0) {
        finish("ok", reviews, totalReviewCount, "");
        return;
      }

      if (totalReviewCount === 0) {
        finish("no_reviews", [], 0, "");
        return;
      }

      finish(
        "error",
        [],
        totalReviewCount,
        "Không lấy được review. Có thể Shopee đang bắt login/captcha hoặc review chưa hiện.",
      );
    } catch (error) {
      finish(
        "error",
        [],
        null,
        error instanceof Error ? error.message : "Không lấy được review do lỗi không xác định.",
      );
    }
  });
}
