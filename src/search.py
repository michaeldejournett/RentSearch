"""
Apartment listing discovery via DuckDuckGo search + best-effort page scraping.
JS-heavy sites are scraped with a stealth Playwright browser.
"""

import datetime
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import RatelimitException

MAX_RESULTS_PER_QUERY = 12
SCRAPE_TIMEOUT = 10
SCRAPE_DELAY = 0.6

# Short-term / vacation rental sites — always skip, we only want long-term rentals
SHORT_TERM_DOMAINS = {
    "airbnb.com",
    "vrbo.com",
    "homeaway.com",
    "vacasa.com",
    "booking.com",
    "expedia.com",
    "tripadvisor.com",
    "hipcamp.com",
    "furnished finder.com",
    "sonder.com",
    "vacationrentals.com",
    "flipkey.com",
}

JS_HEAVY_DOMAINS = {
    "zillow.com",
    "apartments.com",
    "trulia.com",
    "realtor.com",
    "hotpads.com",
    "zumper.com",
    "apartmentlist.com",
    "forrent.com",
    "craigslist.org",
}

# Phrases that indicate a bot-block or CAPTCHA page rather than real content
_BLOCK_PHRASES = {
    "access denied", "captcha", "just a moment", "checking your browser",
    "please enable javascript", "verify you are human", "403 forbidden",
    "are you a robot", "cloudflare", "security check", "enable cookies",
}

# Script injected before page load to hide automation signals
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}};
"""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


_LOG_PATH = Path.home() / "RentSearch" / "scrape_debug.log"

# Domains that returned 403/block during this session — skip on subsequent requests
_blocked_domains: set[str] = set()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_domain_blocked(url: str) -> bool:
    return _domain(url) in _blocked_domains


def _mark_domain_blocked(url: str) -> None:
    host = _domain(url)
    if host not in _blocked_domains:
        _blocked_domains.add(host)
        _scrape_log(url, "SKIP-DOM", f"domain {host} marked as blocked for this session")


def _scrape_log(url: str, status: str, detail: str = "") -> None:
    """Append one line to the scrape debug log and print to console."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {status:<8} {url[:90]}"
    if detail:
        line += f"  ({detail})"
    print(line)
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def is_js_heavy(url: str) -> bool:
    """Return True if the URL belongs to a JS-heavy domain that resists scraping."""
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("." + d) for d in JS_HEAVY_DOMAINS)
    except Exception:  # noqa: BLE001
        return False


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Run a DuckDuckGo text search with exponential backoff on rate limits.
    Raises RuntimeError if all attempts fail.
    """
    backoff = [2, 4, 8]
    last_exc: Exception = RuntimeError("DDG search failed")
    for attempt, wait in enumerate([0] + backoff):
        if wait:
            time.sleep(wait)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return results
        except RatelimitException as e:
            last_exc = e
            if attempt >= len(backoff):
                break
        except Exception as e:  # noqa: BLE001
            last_exc = e
            break
    raise RuntimeError(f"DuckDuckGo search unavailable: {last_exc}") from last_exc


def _extract_page_text(html: str) -> Optional[str]:
    """Extract cleaned body text from an HTML string."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id="content")
        or soup.find(class_="content")
        or soup.body
    )
    if not body:
        return None
    return " ".join(body.get_text(separator=" ").split())


def _find_subpage_links(html: str, base_url: str, max_links: int = 3) -> list[str]:
    """Return URLs that are sub-pages of base_url's path (one level deeper, same domain).
    Prioritises pages whose path/text suggests rental detail content.
    """
    _SUBPAGE_KEYWORDS = {
        "floor", "plan", "amenity", "amenities", "detail", "unit",
        "feature", "overview", "lease", "available", "photo", "gallery",
    }
    try:
        parsed_base = urlparse(base_url)
        base_host = parsed_base.netloc.lower()
        base_path = parsed_base.path.rstrip("/")

        soup = BeautifulSoup(html, "lxml")
        candidates: list[str] = []
        seen: set[str] = set()

        base_depth = len([p for p in base_path.split("/") if p])

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("/"):
                href = f"{parsed_base.scheme}://{base_host}{href}"
            if not href.startswith("http"):
                continue
            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host:
                continue
            path = parsed.path.rstrip("/")
            if path == base_path:
                continue
            # Must be deeper than the current page
            depth = len([p for p in path.split("/") if p])
            if depth <= base_depth:
                continue
            # Skip navigation/utility pages
            if any(path.lower().startswith(skip) for skip in _NAV_SKIP):
                continue
            norm = path.lower()
            if norm in seen:
                continue
            seen.add(norm)
            # Only follow if path or anchor text matches a listing-detail keyword
            text_hint = (a.get_text() + path).lower()
            if any(kw in text_hint for kw in _SUBPAGE_KEYWORDS):
                candidates.insert(0, href)

        return candidates[:max_links]
    except Exception:  # noqa: BLE001
        return []


def _fetch_html(url: str) -> Optional[str]:
    """Fetch raw HTML, falling back to cloudscraper on 403/429 (Cloudflare bypass).
    Returns raw HTML string or None on failure. Does NOT mark domains blocked.
    """
    time.sleep(SCRAPE_DELAY)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=SCRAPE_TIMEOUT)
        if resp.status_code not in (403, 401, 429):
            resp.raise_for_status()
            return resp.text
    except Exception:  # noqa: BLE001
        pass

    # Fallback: cloudscraper handles Cloudflare JS challenges
    try:
        import cloudscraper  # noqa: PLC0415
        scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})
        resp = scraper.get(url, timeout=SCRAPE_TIMEOUT + 5)
        if resp.ok:
            _scrape_log(url, "CF-OK", f"cloudscraper {resp.status_code}")
            return resp.text
    except Exception:  # noqa: BLE001
        pass

    return None


def scrape_page(url: str) -> Optional[str]:
    """Fetch a page and return its cleaned text content, or None on failure."""
    if _is_domain_blocked(url):
        _scrape_log(url, "SKIP", "domain blocked")
        return None
    try:
        html = _fetch_html(url)
        if not html:
            _scrape_log(url, "FAIL", "no HTML retrieved")
            return None
        text = _extract_page_text(html)
        if not text:
            _scrape_log(url, "EMPTY", "no body element")
            return None
        _scrape_log(url, "OK", f"{len(text)} chars")
        return text[:6000]
    except Exception as exc:  # noqa: BLE001
        _scrape_log(url, "FAIL", str(exc)[:80])
        return None


def scrape_listing_deep(url: str, max_subpages: int = 3) -> Optional[str]:
    """Scrape an individual listing page and up to max_subpages sub-pages
    (floor plans, amenities, etc.) to gather as much detail as possible.
    Returns combined text, or None if the main page fails.
    """
    if _is_domain_blocked(url):
        _scrape_log(url, "SKIP", "domain blocked")
        return None

    html = _fetch_html(url)
    if not html:
        _scrape_log(url, "FAIL", "no HTML retrieved")
        return None

    main_text = _extract_page_text(html)
    if not main_text:
        _scrape_log(url, "EMPTY", "no body element")
        return None

    _scrape_log(url, "OK", f"{len(main_text)} chars")
    parts = [main_text[:4000]]  # reserve room for sub-page text

    subpage_urls = _find_subpage_links(html, url, max_links=max_subpages)
    for sub_url in subpage_urls:
        if _is_domain_blocked(sub_url):
            continue
        sub_html = _fetch_html(sub_url)
        if not sub_html:
            continue
        sub_text = _extract_page_text(sub_html)
        if sub_text and len(sub_text) > 100:
            _scrape_log(sub_url, "SUB-OK", f"{len(sub_text)} chars")
            parts.append(sub_text[:1500])

    combined = " | ".join(parts)
    return combined[:7000]


def _scrape_with_playwright(url: str) -> Optional[str]:
    """Render a JS-heavy page with a stealth headless Chromium browser.
    Returns None if Playwright is not installed, the page fails, or bot-blocking is detected.
    """
    if _is_domain_blocked(url):
        _scrape_log(url, "SKIP", "domain blocked")
        return None
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        _scrape_log(url, "SKIP", "playwright not installed")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                ],
            )
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 720},
                locale="en-US",
                timezone_id="America/Chicago",
                java_script_enabled=True,
            )
            pg = ctx.new_page()
            pg.add_init_script(_STEALTH_JS)

            # Block images and media only — keep CSS/fonts for proper JS rendering
            pg.route(
                "**/*.{png,jpg,jpeg,gif,webp,ico,mp4,mp3,avi,webm}",
                lambda r: r.abort(),
            )

            # Try networkidle first; fall back to domcontentloaded on timeout
            try:
                pg.goto(url, wait_until="networkidle", timeout=25_000)
            except Exception:  # noqa: BLE001
                try:
                    pg.reload(wait_until="domcontentloaded", timeout=15_000)
                    pg.wait_for_timeout(3_000)
                except Exception:  # noqa: BLE001
                    browser.close()
                    _scrape_log(url, "FAIL", "navigation timeout")
                    return None

            text = pg.inner_text("body")
            browser.close()

        if not text or len(text.strip()) < 200:
            _scrape_log(url, "EMPTY", f"{len(text or '')} chars")
            return None

        lower = text.lower()[:600]
        for phrase in _BLOCK_PHRASES:
            if phrase in lower:
                _mark_domain_blocked(url)
                _scrape_log(url, "BLOCKED", phrase)
                return None

        cleaned = " ".join(text.split())
        _scrape_log(url, "OK", f"{len(cleaned)} chars")
        return cleaned[:6000]

    except Exception as exc:  # noqa: BLE001
        _scrape_log(url, "ERROR", str(exc)[:120])
        return None


_NAV_SKIP = {
    "/about", "/contact", "/help", "/faq", "/login", "/signup",
    "/search", "/blog", "/careers", "/press", "/terms", "/privacy",
    "/storage", "/campus", "/neighborhood", "/zip-code", "/zip_code",
    "/news", "/guide", "/trends", "/renters-guide", "/resources",
    "/sitemap", "/advertise", "/partners",
}

_LISTING_KEYWORDS = {
    "apartment", "rent", "lease", "unit", "bed", "bath", "sqft",
    "homedetail", "rental", "property", "listing",
}


def _extract_listing_links(html: str, base_url: str, limit: int = 6) -> list[str]:
    """Parse HTML and return up to `limit` individual listing URLs deeper than base_url.
    Shared by both the Playwright and requests-based harvesters.
    """
    try:
        parsed_base = urlparse(base_url)
        base_host = parsed_base.netloc.lower()
        base_depth = len([p for p in parsed_base.path.rstrip("/").split("/") if p])

        soup = BeautifulSoup(html, "lxml")
        candidates: list[str] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("/"):
                href = f"{parsed_base.scheme}://{base_host}{href}"
            if not href.startswith("http"):
                continue

            parsed = urlparse(href)
            if parsed.netloc.lower() != base_host:
                continue
            path = parsed.path.rstrip("/")
            depth = len([p for p in path.split("/") if p])
            if depth <= base_depth:
                continue
            if any(path.lower().startswith(skip) for skip in _NAV_SKIP):
                continue
            if not path or path == parsed_base.path:
                continue

            norm = href.split("?")[0].split("#")[0].rstrip("/").lower()
            if norm in seen:
                continue
            seen.add(norm)

            text_hint = (a.get_text() + path).lower()
            if any(kw in text_hint for kw in _LISTING_KEYWORDS):
                candidates.insert(0, href)
            else:
                candidates.append(href)

        return candidates[:limit]
    except Exception:  # noqa: BLE001
        return []


def _harvest_links_simple(url: str) -> list[str]:
    """Fetch a non-JS page with requests and return individual listing URLs.
    Used for direct (non-aggregator) results that look like list pages.
    Returns [] on any failure.
    """
    try:
        time.sleep(SCRAPE_DELAY)
        resp = requests.get(url, headers=HEADERS, timeout=SCRAPE_TIMEOUT)
        resp.raise_for_status()
        found = _extract_listing_links(resp.text, url)
        _scrape_log(url, "HARVEST", f"{len(found)} links (simple)")
        return found
    except Exception:  # noqa: BLE001
        return []


def _looks_like_list_page(url: str) -> bool:
    """Heuristic: True if the URL looks like a search-results or list page
    rather than an individual listing.
    """
    path = urlparse(url).path.lower().rstrip("/")
    list_patterns = {
        "/search", "/apartments", "/for-rent", "/rentals", "/listings",
        "/results", "/find", "/browse", "/homes",
    }
    return (
        any(path == p or path.startswith(p + "/") or path.endswith(p) for p in list_patterns)
        or path.count("/") <= 1          # very shallow path → likely a category page
        or "?" in url                    # query-string URLs are usually search results
    )


def _harvest_listing_links(url: str) -> list[str]:
    """Render a JS-heavy aggregator page with Playwright and return
    individual listing URLs found on it.  Returns [] on any failure.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        return []

    html = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            pg = ctx.new_page()
            pg.add_init_script(_STEALTH_JS)
            pg.route("**/*.{png,jpg,jpeg,gif,webp,ico,mp4,mp3}", lambda r: r.abort())
            try:
                pg.goto(url, wait_until="networkidle", timeout=25_000)
            except Exception:  # noqa: BLE001
                try:
                    pg.goto(url, wait_until="domcontentloaded", timeout=15_000)
                    pg.wait_for_timeout(2_000)
                except Exception:  # noqa: BLE001
                    browser.close()
                    return []
            html = pg.content()
            browser.close()
    except Exception:  # noqa: BLE001
        return []

    if not html:
        return []

    found = _extract_listing_links(html, url)
    _scrape_log(url, "HARVEST", f"{len(found)} links extracted")
    return found


def _build_queries(
    city: str,
    min_price: int,
    max_price: int,
    min_beds: int,
    max_beds: int,
) -> list[str]:
    """Generate varied DDG-compatible search queries to maximise listing coverage."""
    beds_str = (
        "studio OR 1 bedroom OR 2 bedroom"
        if min_beds == 0
        else f"{min_beds} bedroom" if min_beds == max_beds
        else f"{min_beds} to {max_beds} bedroom"
    )
    price_str = f"${min_price} to ${max_price} per month"
    loc = f" {city.strip()}" if city.strip() else ""
    return [
        f"long term apartments for rent{loc} {beds_str} {price_str} monthly lease",
        f"{city.strip() + ' ' if city.strip() else ''}apartment rentals {beds_str} annual lease",
        f"craigslist{loc} apartments rent {beds_str}",
        f"rentals.com{loc} apartments {beds_str}",
    ]


def _deduplicate(results: list[dict]) -> list[dict]:
    """Remove results with duplicate URLs (normalised)."""
    seen: set[str] = set()
    unique = []
    for r in results:
        url = r.get("href", "").rstrip("/").lower()
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique


def _llm_classify_and_expand(
    results: list[dict],
    city: str,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """Use LLM to classify DDG results as individual listings vs. search pages.
    For search/list pages the LLM generates follow-up DDG queries to find
    actual individual listings.  Returns a refined, deduplicated result list.
    """
    try:
        from .analyzer import _call_llm, parse_json_response  # noqa: PLC0415
    except ImportError:
        return results

    if progress_callback:
        progress_callback(0.38, "AI is identifying individual listing URLs...")

    sample = results[:30]  # keep prompt size reasonable
    lines = []
    for i, r in enumerate(sample, 1):
        lines.append(
            f'{i}. Title: "{r.get("title", "")[:80]}"\n'
            f'   URL: {r.get("href", "")[:120]}\n'
            f'   Snippet: "{r.get("body", "")[:150]}"'
        )

    prompt = (
        f'I am searching for apartment rentals to rent in {city or "a US city"}.\n'
        f'Below are search engine results. Classify each as:\n'
        f'- "LISTING": a page for one specific apartment/unit/complex in the correct location\n'
        f'- "SEARCH": a search-results, category, or list page in the correct location\n'
        f'- "IRRELEVANT": wrong country, wrong city/region, short-term/vacation rental '
        f'(Airbnb, VRBO, hotels, etc.), non-rental content, or unrelated site\n\n'
        f'This is for LONG-TERM rentals only (month-to-month or annual leases). '
        f'Mark any short-term, nightly, or vacation rental as IRRELEVANT.\n'
        f'Results:\n' + "\n".join(lines) + "\n\n"
        f'For every SEARCH result, also provide a specific DuckDuckGo query that would find '
        f'individual apartment listing pages from that same source '
        f'(use "site:domain" when helpful, include city and bedroom/price context).\n\n'
        f'Reply ONLY with a JSON array, one object per result:\n'
        f'[{{"idx":1,"type":"LISTING"}},{{"idx":2,"type":"SEARCH",'
        f'"query":"site:craigslist.org omaha ne 2br apartment rent"}},'
        f'{{"idx":3,"type":"IRRELEVANT"}}]'
    )

    try:
        raw = _call_llm(model, prompt, api_key, base_url, max_tokens=2000)
        data = parse_json_response(raw)
        if not isinstance(data, list):
            return results

        type_map = {
            item["idx"]: item
            for item in data
            if isinstance(item, dict) and "idx" in item
        }

        individual = [
            r for i, r in enumerate(sample, 1)
            if type_map.get(i, {}).get("type") == "LISTING"
        ]
        follow_up_queries = list({
            item["query"]
            for item in data
            if item.get("type") == "SEARCH" and item.get("query", "").strip()
        })
        irrelevant_count = sum(1 for item in data if item.get("type") == "IRRELEVANT")

        _scrape_log("LLM-CLASSIFY", "OK",
                    f"{len(individual)} listings, {len(follow_up_queries)} follow-ups, "
                    f"{irrelevant_count} irrelevant dropped")

        # Ensure every follow-up query includes the city so DDG stays on-target
        if city:
            follow_up_queries = [
                q if city.lower().split(",")[0].strip() in q.lower() else f"{q} {city}"
                for q in follow_up_queries
            ]

        # Run LLM-generated follow-up queries to find individual listing pages
        follow_up_results: list[dict] = []
        for query in follow_up_queries[:10]:
            try:
                if progress_callback:
                    progress_callback(0.40, f"AI follow-up: {query[:70]}...")
                new = _ddg_search(query, max_results=8)
                # Drop short-term domains and obviously foreign results
                new = [
                    r for r in new
                    if not any(
                        _domain(r.get("href", "")) == d or _domain(r.get("href", "")).endswith("." + d)
                        for d in SHORT_TERM_DOMAINS
                    )
                ]
                if city:
                    city_lower = city.lower().split(",")[0].strip()
                    new = [
                        r for r in new
                        if city_lower in (r.get("title", "") + r.get("body", "") + r.get("href", "")).lower()
                        or not r.get("href", "")  # keep if no href to check
                    ]
                follow_up_results.extend(new)
                time.sleep(1.0)
            except Exception:  # noqa: BLE001
                pass

        # Any results beyond the LLM sample pass through unchanged
        remainder = results[30:]
        combined = _deduplicate(individual + follow_up_results + remainder)
        return combined if combined else results

    except Exception as exc:  # noqa: BLE001
        _scrape_log("LLM-CLASSIFY", "FAIL", str(exc)[:80])
        return results


def search_listings(
    city: str,
    min_price: int,
    max_price: int,
    min_beds: int,
    max_beds: int,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
) -> list[dict]:
    """Search DuckDuckGo for apartment listings and attempt page scraping.

    Returns a list of dicts with keys:
        title, href, body (DDG snippet), page_text (scraped or None), scraped (bool)
    Raises RuntimeError if DDG returns nothing at all.
    """
    queries = _build_queries(city, min_price, max_price, min_beds, max_beds)
    raw: list[dict] = []

    for i, query in enumerate(queries):
        if progress_callback:
            progress_callback(i / len(queries) * 0.4, f"Searching: {query[:60]}...")
        try:
            results = _ddg_search(query, MAX_RESULTS_PER_QUERY)
            raw.extend(results)
        except RuntimeError:
            pass  # one query failing is acceptable; continue with others

        if i < len(queries) - 1:
            time.sleep(1.0)  # reduce DDG rate-limiting between queries

    if not raw:
        raise RuntimeError(
            "DuckDuckGo returned no search results. "
            "Check your internet connection or try again in a minute."
        )

    all_results = _deduplicate(raw)
    # Drop short-term/vacation rental sites before any further processing
    all_results = [
        r for r in all_results
        if not any(
            _domain(r.get("href", "")) == d or _domain(r.get("href", "")).endswith("." + d)
            for d in SHORT_TERM_DOMAINS
        )
    ]
    _scrape_log("--- NEW SEARCH ---", "START", f"{len(all_results)} DDG results")

    # ---- Phase 0: LLM classifies results and generates follow-up queries ----
    if api_key and model:
        all_results = _llm_classify_and_expand(
            all_results, city, api_key, model, base_url, progress_callback
        )
        all_results = _deduplicate(all_results)
        _scrape_log("--- POST-LLM ---", "INFO", f"{len(all_results)} results after AI refinement")

    # ---- Phase 1: harvest individual listing URLs from aggregator pages ----
    aggregator_results = [r for r in all_results if is_js_heavy(r.get("href", ""))]
    direct_results   = [r for r in all_results if not is_js_heavy(r.get("href", ""))]

    harvested: list[dict] = []

    # JS-heavy aggregators: use Playwright to harvest individual listing links
    for agg in aggregator_results[:5]:
        agg_url = agg.get("href", "")
        if not agg_url:
            continue
        if progress_callback:
            progress_callback(0.3, f"Harvesting links from {urlparse(agg_url).netloc}...")
        links = _harvest_listing_links(agg_url)
        for link in links:
            harvested.append({
                "title": agg.get("title", ""),
                "href":  link,
                "body":  agg.get("body", ""),
            })

    # Direct results that look like list/search pages: harvest with plain requests
    real_direct: list[dict] = []
    for result in direct_results:
        result_url = result.get("href", "")
        if result_url and _looks_like_list_page(result_url):
            if progress_callback:
                progress_callback(0.35, f"Harvesting links from {urlparse(result_url).netloc}...")
            links = _harvest_links_simple(result_url)
            if links:
                for link in links:
                    harvested.append({
                        "title": result.get("title", ""),
                        "href":  link,
                        "body":  result.get("body", ""),
                    })
                continue  # replaced by individual links — drop the list-page URL
        real_direct.append(result)

    # Combine: individual direct results + harvested individual links
    listings = _deduplicate(real_direct + harvested)
    total = len(listings)

    if progress_callback:
        progress_callback(0.4, f"Found {total} listings to scrape...")

    # ---- Phase 2: scrape each individual listing page (+ sub-pages) ----
    for i, listing in enumerate(listings):
        url = listing.get("href", "")
        if url:
            if is_js_heavy(url):
                listing["page_text"] = _scrape_with_playwright(url)
            else:
                listing["page_text"] = scrape_listing_deep(url)
                # Fallback to Playwright if requests got nothing useful
                if not listing["page_text"]:
                    listing["page_text"] = _scrape_with_playwright(url)
            listing["scraped"] = listing["page_text"] is not None
        else:
            listing["page_text"] = None
            listing["scraped"] = False
            _scrape_log("(no url)", "SKIP", listing.get("title", "")[:60])

        if progress_callback:
            frac = 0.4 + (i + 1) / max(total, 1) * 0.2
            status = "scraped" if listing["scraped"] else "snippet only"
            progress_callback(frac, f"Scraped {i + 1}/{total} ({status})...")

    return listings
