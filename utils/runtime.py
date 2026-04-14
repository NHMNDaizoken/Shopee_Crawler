import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def detect_chrome_path() -> str | None:
    candidates = [
        os.getenv("SHOPEE_CHROME_PATH"),
        os.getenv("CHROME_EXECUTABLE"),
        os.getenv("GOOGLE_CHROME_BIN"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


@dataclass
class RuntimePaths:
    project_root: Path
    data_dir: Path
    output_dir: Path
    shops_file: Path
    profile_dir: Path
    shop_detail_file: Path
    product_detail_file: Path
    review_samples_file: Path


class RuntimeConfig:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[1]
        self.paths = RuntimePaths(
            project_root=self.project_root,
            data_dir=self.project_root / "data",
            output_dir=self.project_root / "output",
            shops_file=self.project_root / "shops.txt",
            profile_dir=Path(os.getenv("SHOPEE_PROFILE_DIR", self.project_root / "shopee_profile_chrome")),
            shop_detail_file=self.project_root / "data" / "shop_detail.csv",
            product_detail_file=self.project_root / "data" / "pdp_detail.csv",
            review_samples_file=self.project_root / "data" / "product_review_samples.csv",
        )
        self.chrome_path = detect_chrome_path()
        self.chrome_port = _env_int("SHOPEE_CHROME_PORT", 9222)
        self.shop_finder_port = _env_int("SHOPEE_SHOP_FINDER_PORT", 9234)
        self.auto_find_shops = _env_flag("SHOPEE_AUTO_FIND_SHOPS", False)
        self.shop_discovery_mode = os.getenv("SHOPEE_SHOP_DISCOVERY_MODE", "users").strip().lower()
        self.shop_discovery_limit = _env_int("SHOPEE_SHOP_LIMIT", 100) or 100
        self.shop_keywords = self._load_keywords()
        self.max_shop_pages = _env_int("SHOPEE_MAX_SHOP_PAGES", 1) or 1
        self.product_limit = _env_int("SHOPEE_PRODUCT_LIMIT")
        self.review_only_pending = _env_flag("SHOPEE_REVIEW_ONLY_PENDING", True)
        self.review_skip_sampled = _env_flag("SHOPEE_REVIEW_SKIP_SAMPLED", True)
        self.review_refresh_every = _env_int("SHOPEE_REVIEW_REFRESH_EVERY", 40) or 40
        self.reviews_per_star_sample = _env_int("SHOPEE_REVIEWS_PER_STAR", 5) or 5
        self.review_itemids = self._load_int_set("SHOPEE_REVIEW_ITEMIDS")
        self.review_start_index = max((_env_int("SHOPEE_REVIEW_START_INDEX", 0) or 0), 0)

    def _load_keywords(self) -> list[str]:
        raw = os.getenv("SHOPEE_KEYWORDS", "")
        return [item.strip() for item in raw.split("|") if item.strip()]

    def _load_int_set(self, name: str) -> set[int]:
        raw = os.getenv(name, "")
        values = set()
        for item in raw.replace(";", ",").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                values.add(int(item))
            except ValueError:
                continue
        return values

    def ensure_dirs(self):
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.profile_dir.mkdir(parents=True, exist_ok=True)


runtime = RuntimeConfig()
