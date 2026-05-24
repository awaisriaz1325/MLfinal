import argparse
import json
import random
import copy
import sys
from pathlib import Path
import time

from patchright.sync_api import TimeoutError as PlaywrightTimeoutError
from patchright.sync_api import sync_playwright

try:
    import boto3
except ImportError:
    boto3 = None


def upload_to_s3(local_path: str, bucket: str, s3_key: str) -> bool:
    if not boto3:
        print("[s3] boto3 not installed, skipping upload")
        return False
    try:
        s3 = boto3.client("s3")
        s3.upload_file(local_path, bucket, s3_key)
        print(f"[s3] uploaded {local_path} -> s3://{bucket}/{s3_key}")
        return True
    except Exception as e:
        print(f"[s3] upload failed: {e}")
        return False

DEFAULT_URLS = [
    "https://www.wayfair.com/outdoor/pdp/fleur-de-lis-living-rusty-bicyclette-outdoor-wall-decor-w004779595.html?auctionId=e82d1ea4-c761-4066-aca7-bdd30114ce85&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22e82d1ea4-c761-4066-aca7-bdd30114ce85%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/luxen-home-butterfly-outdoor-wall-decor-hxuo1819.html?auctionId=e82d1ea4-c761-4066-aca7-bdd30114ce85&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22e82d1ea4-c761-4066-aca7-bdd30114ce85%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/red-barrel-studio-chauntrice-sweet-harmony-outdoor-wall-canvas-art-w010558434.html?auctionId=e82d1ea4-c761-4066-aca7-bdd30114ce85&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22e82d1ea4-c761-4066-aca7-bdd30114ce85%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/winston-porter-chaunice-wall-accent-w008500898.html?piid=601623681%2C601623742&auctionId=e82d1ea4-c761-4066-aca7-bdd30114ce85&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22e82d1ea4-c761-4066-aca7-bdd30114ce85%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/macmillan-annelein-beukenkamp-sun-shower-wall-decor-w009311870.html?piid=428907447",
    "https://www.wayfair.com/outdoor/pdp/trinx-marion-rose-spirit-of-the-prairie-outdoor-all-weather-wall-decor-w009312308.html?piid=1092511663",
    "https://www.wayfair.com/outdoor/pdp/sundown-outdoor-canvas-art-wou10284.html",
    "https://www.wayfair.com/outdoor/pdp/millwood-pines-homestead-32-wood-wagon-wheel-wall-decor-set-of-2-xsh1050.html",
    "https://www.wayfair.com/outdoor/pdp/red-barrel-studio-dasie-blue-pots-outdoor-wall-canvas-art-w010560449.html?auctionId=ef015ba8-f7ec-45c4-aee0-78e0e055767e&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22ef015ba8-f7ec-45c4-aee0-78e0e055767e%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/trinx-imanuel-wall-decor-w100571308.html?auctionId=ef015ba8-f7ec-45c4-aee0-78e0e055767e&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22ef015ba8-f7ec-45c4-aee0-78e0e055767e%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/red-barrel-studio-exaltacin-rainforest-outdoor-wall-decor-w004621747.html?auctionId=ef015ba8-f7ec-45c4-aee0-78e0e055767e&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22ef015ba8-f7ec-45c4-aee0-78e0e055767e%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/red-barrel-studio-lino-jamboree-garden-outdoor-wall-decor-w002860451.html?auctionId=ef015ba8-f7ec-45c4-aee0-78e0e055767e&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22ef015ba8-f7ec-45c4-aee0-78e0e055767e%22}&adTypeId=1",
    "https://www.wayfair.com/outdoor/pdp/wade-logan-arusa-jane-deakin-valley-of-the-waterfalls-outdoor-all-weather-wall-decor-w009312555.html?piid=1222846375",
]

def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.split())


def parse_int_from_text(value: str | None) -> int:
    if not value:
        return 0
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else 0


def parse_rating_value(value: str | None) -> float | None:
    if not value:
        return None
    token = "".join(ch if (ch.isdigit() or ch == ".") else " " for ch in value).split()
    if not token:
        return None
    try:
        return float(token[0])
    except ValueError:
        return None

def safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_message = message.encode(encoding, errors="backslashreplace").decode(
            encoding, errors="ignore"
        )
        print(safe_message)


def first_text(page, selector: str) -> str | None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return None
    return clean_text(locator.inner_text())


def first_attr(page, selector: str, attr: str) -> str | None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return None
    return locator.get_attribute(attr)


def wait_for_page_ready(page) -> None:
    page.wait_for_load_state("domcontentloaded", timeout=45000)
    page.wait_for_timeout(1200)


def handle_blocked_access(page) -> bool:
    print("[captcha] checking for blocked access marker (#px-captcha-wrapper)")
    try:
        marker_found = False
        marker_frame = None
        for _ in range(30):
            for frame in page.frames:
                try:
                    if frame.locator("#px-captcha-wrapper").count() > 0:
                        marker_found = True
                        marker_frame = frame
                        break
                except Exception:
                    continue
            if marker_found:
                break
            page.wait_for_timeout(100)

        if not marker_found:
            print("[captcha] marker not found in any frame within 3s, continuing scrape")
            return False
        print(f"[captcha] marker detected in frame: {marker_frame.url if marker_frame else 'unknown'}")
        print("[captcha] marker detected, attempting press-and-hold")

        print("[captcha] searching frames for press-and-hold button")
        challenge_button = None
        challenge_frame = None
        for _ in range(100):
            for frame in page.frames:
                try:
                    button = frame.locator('[aria-label="Press & Hold"]').first
                    if button.count() > 0:
                        challenge_button = button
                        challenge_frame = frame
                        break
                except Exception:
                    continue
            if challenge_button:
                break
            page.wait_for_timeout(100)

        if not challenge_button:
            print("[captcha] failed: press-and-hold button not found in any frame")
            return False

        print(f"[captcha] button found in frame: {challenge_frame.url if challenge_frame else 'unknown'}")
        challenge_button.scroll_into_view_if_needed(timeout=10000)
        challenge_button.hover()
        page.wait_for_timeout(random.randint(100, 250))

        box = challenge_button.bounding_box()
        if not box:
            print("[captcha] failed: no bounding box")
            return False

        x = box["x"] + (box["width"] / 2)
        y = box["y"] + (box["height"] / 2)
        print(f"[captcha] holding at x={x:.1f}, y={y:.1f} for 10s")
        page.mouse.move(
            x + random.uniform(-5, 5),
            y + random.uniform(-5, 5),
            steps=random.randint(20, 35)
        )
        page.wait_for_timeout(random.randint(100, 250))
        page.mouse.down()
        hold_duration = random.uniform(8.5, 12.5)
        start = time.time()

        # micro-movements while holding
        while time.time() - start < hold_duration:
            jitter_x = x + random.uniform(-2, 2)
            jitter_y = y + random.uniform(-2, 2)

            page.mouse.move(jitter_x, jitter_y, steps=random.randint(1, 3))
            page.wait_for_timeout(random.randint(80, 160))
            
        page.mouse.up()
        page.wait_for_timeout(1000)
        print("[captcha] hold released")
        solved = False
        for _ in range(30):
            still_there = False
            for frame in page.frames:
                try:
                    if frame.locator("#px-captcha-wrapper").count() > 0:
                        still_there = True
                        break
                except Exception:
                    continue

            if not still_there:
                solved = True
                break

            page.wait_for_timeout(500)

        if solved:
            print("[captcha] solved successfully")
        else:
            print("[captcha] captcha still present after attempt")

        return solved
    except Exception as exc:
        print(f"[captcha] detector error ignored: {exc}")
        return False


def act_like_user(page) -> None:
    page.mouse.move(random.randint(320, 620), random.randint(180, 360), steps=28)
    page.wait_for_timeout(random.randint(180, 320))
    for _ in range(3):
        page.mouse.wheel(0, random.randint(90, 150))
        page.wait_for_timeout(random.randint(140, 220))


def click_in_view(page, selector: str, timeout: int = 10000) -> bool:
    target = page.locator(selector).first
    if target.count() == 0:
        return False
    target.scroll_into_view_if_needed(timeout=timeout)
    target.click(timeout=timeout)
    return True


def smooth_scroll_to(page, selector: str) -> bool:
    target = page.locator(selector).first
    if target.count() == 0:
        return False

    distance = target.evaluate(
        """(el) => {
            const margin = 200;
            const r = el.getBoundingClientRect();
            const docTop = r.top + window.scrollY;
            const want = Math.max(0, docTop - margin);
            return want - window.scrollY;
        }"""
    )
    if not isinstance(distance, (int, float)):
        return False
    if abs(distance) < 16:
        target.scroll_into_view_if_needed(timeout=10000)
        page.wait_for_timeout(60)
        return True

    steps = max(6, min(18, int(abs(distance) / 280) + 6))
    step = float(distance) / steps
    pause_ms = 48
    for _ in range(steps):
        page.mouse.wheel(0, step)
        page.wait_for_timeout(pause_ms)

    target.scroll_into_view_if_needed(timeout=10000)
    page.wait_for_timeout(70)
    return True


def extract_clean_html(page, selector: str) -> str | None:
    return page.evaluate(
        """(sel) => {
            const root = document.querySelector(sel);
            if (!root) return null;
            const clone = root.cloneNode(true);
            const keepAttrs = new Set(["href", "src", "alt", "title", "colspan", "rowspan"]);
            const walker = document.createTreeWalker(clone, NodeFilter.SHOW_ELEMENT);
            let node = walker.currentNode;
            while (node) {
                const attrs = Array.from(node.attributes || []);
                for (const attr of attrs) {
                    if (!keepAttrs.has(attr.name)) {
                        node.removeAttribute(attr.name);
                    }
                }
                node = walker.nextNode();
            }
            return clone.outerHTML;
        }""",
        selector,
    )


def extract_specifications_html(page) -> str | None:
    toggle = page.locator('[data-enzyme-id="collapsePanelToggle"]', has_text="Specifications").first
    if toggle.count() == 0:
        return None

    toggle_selector = '[data-enzyme-id="collapsePanelToggle"]:has-text("Specifications")'
    smooth_scroll_to(page, toggle_selector)
    toggle.scroll_into_view_if_needed(timeout=10000)

    is_open = (toggle.get_attribute("aria-expanded") or "").lower() == "true"
    if not is_open:
        page.wait_for_timeout(800)
        toggle.click(timeout=10000)
        page.wait_for_timeout(500)

    html = extract_clean_html(page, '[id="react-collapsed-panel-:Rhsqblafn9pvqpkq:"] ._1dufoct2')
    if html:
        return html
    return extract_clean_html(page, '[id^="react-collapsed-panel-"] ._1dufoct2')

click_in_view
def click_show_more_when_ready(
    page,
    show_more_selector: str,
    wait_enabled_ms: int = 60000,
    click_timeout: int = 20000,
) -> bool:
    ready = page.locator(f"{show_more_selector}:not([disabled])").first
    try:
        ready.wait_for(state="visible", timeout=wait_enabled_ms)
    except PlaywrightTimeoutError:
        return False
    smooth_scroll_to(page, show_more_selector)
    try:
        ready.click(timeout=click_timeout)
    except PlaywrightTimeoutError:
        return False
    return True


def wait_for_reviews_loaded(page, previous_count: int = 0, timeout: int = 30000) -> None:
    page.wait_for_selector('[data-rtl-id^="reviewCard-"]', timeout=timeout)
    if previous_count > 0:
        try:
            page.wait_for_function(
                """(prev) => {
                    return document.querySelectorAll('[data-rtl-id^="reviewCard-"]').length > prev;
                }""",
                arg=previous_count,
                timeout=timeout,
            )
        except PlaywrightTimeoutError:
            pass
    page.wait_for_timeout(1400)


def extract_single_review(page, idx: int) -> dict | None:
    card_selector = f'[data-rtl-id="reviewCard-{idx}"]'
    card = page.locator(card_selector).first
    if card.count() == 0:
        return None

    texts = card.locator('[data-hb-id="Text"]').all_inner_texts()
    cleaned = [clean_text(x) for x in texts if clean_text(x)]
    rating_label = first_text(page, f"{card_selector} [data-rtl-id=\"reviewCardStars-a11yLabel\"]")

    reviewer_name = cleaned[0] if len(cleaned) > 0 else None
    reviewer_location = None
    reviewer_type = None
    review_text = None
    review_date = None

    if len(cleaned) >= 5:
        reviewer_location = cleaned[1]
        reviewer_type = cleaned[2]
        review_text = cleaned[3]
        review_date = cleaned[4]
    elif len(cleaned) == 4:
        reviewer_type = cleaned[1]
        review_text = cleaned[2]
        review_date = cleaned[3]
    elif len(cleaned) == 3:
        reviewer_type = cleaned[1]
        review_text = cleaned[2]
    elif len(cleaned) == 2:
        review_text = cleaned[1]

    return {
        "index": idx,
        "rating": parse_rating_value(rating_label),
        "rating_raw": rating_label,
        "reviewer_name": reviewer_name,
        "reviewer_location": reviewer_location,
        "reviewer_type": reviewer_type,
        "review_text": review_text,
        "review_date": review_date,
    }


def scrape_reviews(page, expected_total: int) -> list[dict]:
    reviews: list[dict] = []
    seen_indices: set[int] = set()
    idle_rounds = 0
    max_idle_rounds = 6

    while True:
        count_before_collect = len(reviews)
        cards = page.locator('[data-rtl-id^="reviewCard-"]')
        card_count = cards.count()
        if card_count:
            for i in range(1, card_count + 1):
                if i in seen_indices:
                    continue
                review = extract_single_review(page, i)
                if review:
                    reviews.append(review)
                    seen_indices.add(i)

        if expected_total > 0 and len(reviews) >= expected_total:
            break

        show_more_selector = '[data-rtl-id="reviewCardShowMore"]'
        if page.locator('text=Sign in').count() > 0:
            print("[reviews] login wall detected, reloading page and retrying")
            page.reload()
            wait_for_page_ready(page)
            continue
        show_more = page.locator(show_more_selector).first
        if show_more.count() == 0:
            break

        if len(reviews) == count_before_collect:
            idle_rounds += 1
            if idle_rounds >= max_idle_rounds:
                break
        else:
            idle_rounds = 0

        before_click = len(reviews)
        if not click_show_more_when_ready(page, show_more_selector):
            break
        wait_for_reviews_loaded(page, previous_count=before_click, timeout=90000)

    return reviews


def scrape_page(page, url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(random.randint(4000, 7000))
    was_blocked = handle_blocked_access(page)
    print(f"[captcha] handler result: {'triggered' if was_blocked else 'not triggered'}")
    wait_for_page_ready(page)
    page.wait_for_timeout(random.randint(3000, 6000))
    act_like_user(page)
    try:
        page.wait_for_selector('[data-rtl-id="listingHeaderNameHeading"]', timeout=30000)
    except PlaywrightTimeoutError:
        pass

    total_reviews_text = first_text(page, '[data-rtl-id="reviewsHeaderReviewsLink"]')
    total_reviews_normalized = parse_int_from_text(total_reviews_text)
    specifications_html = extract_specifications_html(page)
    product_data = {
        "listing_title": first_text(page, '[data-rtl-id="listingHeaderNameHeading"]'),
        "manufacturer_name": first_attr(
            page, '[data-rtl-id="listingManufacturerName"] a', "aria-label"
        ),
        "manufacturer_link": first_attr(
            page, '[data-rtl-id="listingManufacturerName"] a', "href"
        ),
        "average_rating": first_text(page, '[data-rtl-id="reviewsHeaderReviewsAverage"]'),
        "total_reviews": total_reviews_text,
        "total_reviews_normalized": total_reviews_normalized,
        "price": first_text(page, '[data-name="Pricing"] [data-test-id="PriceDisplay"]'),
        "product_image": first_attr(
            page, '[id="pdp-mt-grid"] [data-enzyme-id="FluidImage-wrapper"] img', "src"
        ),
        "description": first_text(page, 'div._6o3atz1d9._6o3atzbl._6o3atz1bd'),
        "specifications_html": specifications_html,
    }

    smooth_scroll_to(page, '[data-rtl-id="reviewsHeaderReviewsLink"]')
    page.wait_for_timeout(500)
    clicked = click_in_view(page, '[data-rtl-id="reviewsHeaderReviewsLink"]')
    page.wait_for_timeout(2000)

    if clicked:
        wait_for_reviews_loaded(page, timeout=30000)

    reviews = scrape_reviews(page, total_reviews_normalized)

    data = {
        "source_url": url,
        **product_data,
        "reviews_count_scraped": len(reviews),
        "reviews": reviews,
    }
    return data

def _extract_reviews_from_graphql_payload(payload: dict) -> tuple[list[dict], int, str | None]:
    reviews_block = (
        payload.get("data", {})
        .get("listingVariant", {})
        .get("reviewslist", {})
        .get("reviews", {})
    )
    edges = reviews_block.get("edges", []) or []
    total_count = reviews_block.get("totalCount") or 0
    end_cursor = (reviews_block.get("pageInfo") or {}).get("endCursor")
    has_next = (reviews_block.get("pageInfo") or {}).get("hasNextPage", False)
    reviews: list[dict] = []
    for idx, edge in enumerate(edges, 1):
        node = edge.get("node", {}) if isinstance(edge, dict) else {}
        reviews.append(
            {
                "index": idx,
                "rating": node.get("rating"),
                "rating_raw": str(node.get("rating")) if node.get("rating") is not None else None,
                "reviewer_name": node.get("reviewerGivenName"),
                "reviewer_location": node.get("reviewerLocation"),
                "reviewer_type": node.get("badge"),
                "review_text": clean_text(node.get("body")),
                "review_date": node.get("formattedDate"),
            }
        )
    return reviews, total_count, end_cursor, has_next


def fetch_all_reviews_via_graphql(
    page,
    captured_request: dict,
    first_payload: dict,
    expected_total: int,
    batch_size: int,
) -> list[dict]:
    """Paginate through all review pages using the browser's fetch() with the
    captured GraphQL request as a template. Cookies and auth headers are
    automatically included because the call runs inside the page context."""
    all_reviews, total_count, end_cursor, has_next = _extract_reviews_from_graphql_payload(first_payload)
    print(f"[reviews] page 1 — got {len(all_reviews)} / {total_count} reviews, has_next={has_next}")

    page_num = 1
    while has_next and end_cursor and len(all_reviews) < (expected_total or total_count or 999999):
        page_num += 1
        # Build next request body: update the 'after' cursor in variables
        next_body = copy.deepcopy(captured_request["body"])
        variables = next_body.get("variables", {})
        variables["after"] = end_cursor
        variables["first"] = batch_size
        next_body["variables"] = variables

        # Run fetch() inside the browser so cookies/session are preserved
        result = page.evaluate(
            """
            async ([url, headers, body]) => {
                try {
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify(body),
                        credentials: 'include',
                    });
                    const text = await resp.text();
                    return { ok: resp.ok, status: resp.status, body: text };
                } catch (e) {
                    return { ok: false, status: 0, body: String(e) };
                }
            }
            """,
            [captured_request["url"], captured_request["headers"], next_body],
        )

        if not result or not result.get("ok"):
            print(f"[reviews] page {page_num} fetch failed: {result}")
            break

        try:
            payload = json.loads(result["body"])
        except Exception as e:
            print(f"[reviews] page {page_num} JSON parse error: {e}")
            break

        batch, _, end_cursor, has_next = _extract_reviews_from_graphql_payload(payload)
        if not batch:
            print(f"[reviews] page {page_num} — empty batch, stopping")
            break

        # Re-index reviews globally
        offset = len(all_reviews)
        for r in batch:
            r["index"] = offset + r["index"]
        all_reviews.extend(batch)
        print(f"[reviews] page {page_num} — got {len(batch)}, total so far {len(all_reviews)} / {total_count}")

    return all_reviews



def scrape_page_request_mode(page, url: str, review_batch_size: int) -> dict:
    capture = {"request": None, "response_json": None}
    target_op = "reviewsListPossibleMPLDataByNodeIdQuery"

    def on_request(req):
        if req.method != "POST" or "/federation/graphql" not in req.url:
            return
        try:
            body_json = req.post_data_json or {}
        except Exception:
            body_json = {}
        if body_json.get("operationName") == target_op:
            capture["request"] = {"url": req.url, "headers": dict(req.headers), "body": body_json}

    def on_response(resp):
        req = resp.request
        if req.method != "POST" or "/federation/graphql" not in req.url:
            return
        try:
            req_body = req.post_data_json or {}
        except Exception:
            req_body = {}
        if req_body.get("operationName") != target_op:
            return
        try:
            body_json = json.loads(resp.text())
        except Exception:
            body_json = None
        if isinstance(body_json, dict):
            capture["response_json"] = body_json

    page.on("request", on_request)
    page.on("response", on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(random.randint(1500, 2500))
    was_blocked = handle_blocked_access(page)
    print(f"[captcha] handler result: {'triggered' if was_blocked else 'not triggered'}")
    wait_for_page_ready(page)
    act_like_user(page)
    page.wait_for_selector('[data-rtl-id="listingHeaderNameHeading"]', timeout=30000)

    total_reviews_text = first_text(page, '[data-rtl-id="reviewsHeaderReviewsLink"]')
    total_reviews_normalized = parse_int_from_text(total_reviews_text)
    specifications_html = extract_specifications_html(page)
    product_data = {
        "listing_title": first_text(page, '[data-rtl-id="listingHeaderNameHeading"]'),
        "manufacturer_name": first_attr(
            page, '[data-rtl-id="listingManufacturerName"] a', "aria-label"
        ),
        "manufacturer_link": first_attr(
            page, '[data-rtl-id="listingManufacturerName"] a', "href"
        ),
        "average_rating": first_text(page, '[data-rtl-id="reviewsHeaderReviewsAverage"]'),
        "total_reviews": total_reviews_text,
        "total_reviews_normalized": total_reviews_normalized,
        "price": first_text(page, '[data-name="Pricing"] [data-test-id="PriceDisplay"]'),
        "product_image": first_attr(
            page, '[id="pdp-mt-grid"] [data-enzyme-id="FluidImage-wrapper"] img', "src"
        ),
        "description": first_text(page, 'div._6o3atz1d9._6o3atzbl._6o3atz1bd'),
        "specifications_html": specifications_html,
    }

    # Edge case: if rating or total-reviews label is missing, skip review checks.
    if not product_data["average_rating"] or not total_reviews_text:
        return {
            "source_url": url,
            **product_data,
            "reviews_count_scraped": 0,
            "reviews": [],
            "mode_used": "request_mode",
            "request_mode_batch_size": max(1, review_batch_size),
        }
    
    if not capture["request"] or not capture["response_json"]:
        if click_in_view(page, '[data-rtl-id="reviewsHeaderReviewsLink"]'):
            # Poll until GraphQL response arrives (max 8s) instead of flat sleep
            for _ in range(160):
                if capture["response_json"]:
                    break
                page.wait_for_timeout(50)

    if not capture["request"] or not capture["response_json"]:
        collected = []
    else:
        collected = fetch_all_reviews_via_graphql(
            page=page,
            captured_request=capture["request"],
            first_payload=capture["response_json"],
            expected_total=total_reviews_normalized,
            batch_size=review_batch_size,
        )

    data = {
        "source_url": url,
        **product_data,
        "reviews_count_scraped": len(collected),
        "reviews": collected,
        "mode_used": "request_mode",
        "request_mode_batch_size": review_batch_size,
    }
    return data


def scrape_partial_page_data(page, url: str, error: str, attempt: int, retryable: bool) -> dict:
    specifications_html = extract_specifications_html(page)
    return {
        "source_url": url,
        "error": error,
        "attempt": attempt,
        "retryable": retryable,
        "listing_title": first_text(page, '[data-rtl-id="listingHeaderNameHeading"]'),
        "manufacturer_name": first_attr(page, '[data-rtl-id="listingManufacturerName"] a', "aria-label"),
        "manufacturer_link": first_attr(page, '[data-rtl-id="listingManufacturerName"] a', "href"),
        "average_rating": first_text(page, '[data-rtl-id="reviewsHeaderReviewsAverage"]'),
        "total_reviews": first_text(page, '[data-rtl-id="reviewsHeaderReviewsLink"]'),
        "price": first_text(page, '[data-name="Pricing"] [data-test-id="PriceDisplay"]'),
        "product_image": first_attr(
            page, '[id="pdp-mt-grid"] [data-enzyme-id="FluidImage-wrapper"] img', "src"
        ),
        "description": first_text(page, 'div._6o3atz1d9._6o3atzbl._6o3atz1bd'),
        "specifications_html": specifications_html,
        "reviews_count_scraped": 0,
        "reviews": [],
    }


def create_context(playwright_instance, profile_dir: Path, headless: bool):
    launch_kwargs = {
        "user_data_dir": str(profile_dir),
        "channel": "chrome",
        "headless": headless,
        "no_viewport": True,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "proxy": {
            "server": "http://superproxy.zenrows.com:1337",
            "username": "pWvcKptjSwmt",
            "password": "iaEhZ5HKkHpi"
        },
        "args": [
            "--disable-blink-features=AutomationControlled",
        ],
    }
    context = playwright_instance.chromium.launch_persistent_context(**launch_kwargs)
    return context


def scrape_with_retries(
    browser_state: dict,
    profile_dir: Path,
    playwright_instance,
    url: str,
    headless: bool,
    max_retries: int,
    mode: str,
    request_batch_size: int,
) -> dict:
    last_partial = {"source_url": url, "error": "Unknown error"}
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[runner] scraping {url} (attempt {attempt}/{max_retries})")
            if browser_state["context"] is None:
                browser_state["context"] = create_context(playwright_instance, profile_dir, headless=headless)
                browser_state["page"] = browser_state["context"].pages[0] if browser_state["context"].pages else browser_state["context"].new_page()
            
            page = browser_state["page"]
            
            if mode == "request_mode":
                result = scrape_page_request_mode(page, url, review_batch_size=request_batch_size)
            else:
                result = scrape_page(page, url)

            if mode == "request_mode":
                total_expected = result.get("total_reviews_normalized")
                total_scraped = result.get("reviews_count_scraped")
                has_review_metadata = bool(result.get("average_rating")) and bool(result.get("total_reviews"))
                if has_review_metadata and isinstance(total_expected, int) and isinstance(total_scraped, int):
                    min_required = int(total_expected * 0.8)

            result["attempt"] = attempt
            result["status"] = "ok"
            return result
        except Exception as exc:
            error_text = str(exc)
            print(f"[runner] failed attempt {attempt}/{max_retries}: {error_text}")
            
            page = browser_state.get("page")
            if page:
                try:
                    last_partial = scrape_partial_page_data(
                        page=page,
                        url=url,
                        error=error_text,
                        attempt=attempt,
                        retryable=attempt < max_retries,
                    )
                except Exception as e2:
                    last_partial = {"source_url": url, "error": f"{error_text} (Partial save error: {e2})", "attempt": attempt, "retryable": attempt < max_retries}
            else:
                last_partial = {"source_url": url, "error": error_text, "attempt": attempt, "retryable": attempt < max_retries}
                
            if browser_state["context"]:
                try:
                    browser_state["context"].close()
                except Exception:
                    pass
                browser_state["context"] = None
                browser_state["page"] = None

    last_partial["status"] = "partial"
    return last_partial

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape product details from Wayfair PDP pages with persistent login."
    )
    parser.add_argument(
        "--url",
        nargs="+",
        default=DEFAULT_URLS,
        help="One or more Wayfair PDP URLs.",
    )
    parser.add_argument(
        "--profile-dir",
        default="playwright_profile",
        help="Folder used for persistent browser profile/session.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode after login profile is saved.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Max retries per URL with browser restart.",
    )
    parser.add_argument(
        "--output",
        default="scrape_results.json",
        help="Path to output JSON file.",
    )
    parser.add_argument(
        "--mode",
        choices=["automation_review", "request_mode"],
        default="request_mode",
        help="Scrape mode: DOM automation flow or GraphQL request-driven flow.",
    )
    parser.add_argument(
        "--request-batch-size",
        type=int,
        default=50,
        help="Review batch size used in request_mode pagination.",
    )
    parser.add_argument(
        "--input-file",
        help="Path to JSON file containing a list of URLs or objects with 'source_url'/'url' keys.",
    )
    parser.add_argument(
        "--slack-webhook",
        help="Slack webhook URL to send periodic notifications.",
    )
    parser.add_argument(
        "--s3-bucket",
        default=None,
        help="S3 bucket name to upload scrape results to.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch --input-file for new URLs and scrape them.",
    )
    parser.add_argument(
        "--watch-interval",
        type=int,
        default=30,
        help="Seconds to wait between re-scanning --input-file in watch mode.",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip interactive login prompt (for EC2/headless environments).",
    )
    args = parser.parse_args()

    profile_dir = Path(args.profile_dir).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    login_marker = profile_dir / ".login_saved"

    # On EC2 (--skip-login), just write the marker and skip interactive login
    if args.skip_login:
        if not login_marker.exists():
            login_marker.write_text("ok", encoding="utf-8")
        is_first_login = False
    else:
        is_first_login = not login_marker.exists()

    def load_urls_from_input_file(path: str) -> list[str]:
        """Read URLs from JSON input file."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            urls = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        urls.append(item)
                    elif isinstance(item, dict):
                        url = item.get("source_url") or item.get("url")
                        if url:
                            urls.append(url)
            return urls
        except Exception as e:
            print(f"[watch] Error reading input file: {e}")
            return []

    # Determine initial target URLs
    if args.input_file:
        target_urls = load_urls_from_input_file(args.input_file)
        if not target_urls and not args.watch:
            print("No URLs found in input file and --watch not set. Exiting.")
            return
    else:
        target_urls = args.url

    with sync_playwright() as p:
        if is_first_login:
            context = create_context(p, profile_dir, headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto("https://www.wayfair.com/", wait_until="domcontentloaded", timeout=90000)
                handle_blocked_access(page)
                wait_for_page_ready(page)
            except Exception as e:
                print(f"[login] pre-login page setup warning (non-fatal): {e}")
            print("First run: log in to Wayfair in the opened browser window.")
            input("After login is complete, press Enter to start scraping...")
            # Write marker immediately so a crash below doesn't force re-login
            login_marker.write_text("ok", encoding="utf-8")
            try:
                page.wait_for_timeout(random.randint(2000, 3000))
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass

        total_products_scraped = 0
        total_reviews_scraped = 0
        output_file = Path(args.output)
        jsonl_output = output_file.with_suffix(".jsonl")

        def send_slack_notification(total_scraped, total_reviews):
            if not args.slack_webhook:
                return
            import urllib.request
            payload = {
                "text": f"Scraping Update: \n- Products Scraped: {total_scraped}\n- Total Reviews Scraped: {total_reviews}"
            }
            req = urllib.request.Request(
                args.slack_webhook,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            try:
                urllib.request.urlopen(req)
                print(f"[slack] Notification sent successfully.")
            except Exception as e:
                print(f"[slack] Failed to send notification: {e}")

        # Track already-scraped URLs across watch cycles
        scraped_urls: set[str] = set()

        # Load already-scraped URLs from existing JSONL to avoid re-scraping
        if jsonl_output.exists():
            try:
                with open(jsonl_output, "r", encoding="utf-8") as f_existing:
                    for line in f_existing:
                        if line.strip():
                            try:
                                record = json.loads(line)
                                url = record.get("source_url")
                                if url:
                                    scraped_urls.add(url)
                            except Exception:
                                pass
                print(f"[resume] Found {len(scraped_urls)} already-scraped URLs in {jsonl_output}")
            except Exception:
                pass

        browser_state = {"context": None, "page": None}

        def scrape_batch(urls_to_scrape: list[str]) -> None:
            nonlocal total_products_scraped, total_reviews_scraped
            with open(jsonl_output, "a", encoding="utf-8") as f_out:
                for target_url in urls_to_scrape:
                    result = scrape_with_retries(
                        browser_state=browser_state,
                        profile_dir=profile_dir,
                        playwright_instance=p,
                        url=target_url,
                        headless=args.headless,
                        max_retries=max(1, args.max_retries),
                        mode=args.mode,
                        request_batch_size=max(1, args.request_batch_size),
                    )

                    f_out.write(json.dumps(result, ensure_ascii=False) + "\n")
                    f_out.flush()
                    scraped_urls.add(target_url)

                    total_products_scraped += 1
                    total_reviews_scraped += result.get("reviews_count_scraped", 0)

                    # Upload JSONL to S3 after every product
                    if args.s3_bucket:
                        upload_to_s3(str(jsonl_output), args.s3_bucket, jsonl_output.name)

                    if total_products_scraped % 40 == 0:
                        send_slack_notification(total_products_scraped, total_reviews_scraped)

        if args.watch and args.input_file:
            # ---- CONTINUOUS WATCH MODE ----
            print(f"[watch] Watching {args.input_file} for new URLs (interval: {args.watch_interval}s)")
            while True:
                all_urls = load_urls_from_input_file(args.input_file)
                new_urls = [u for u in all_urls if u not in scraped_urls]

                if new_urls:
                    print(f"[watch] Found {len(new_urls)} new URLs to scrape (total in file: {len(all_urls)}, already scraped: {len(scraped_urls)})")
                    scrape_batch(new_urls)
                else:
                    print(f"[watch] No new URLs. {len(scraped_urls)} scraped, {len(all_urls)} in file. Sleeping {args.watch_interval}s...")

                time.sleep(args.watch_interval)
        else:
            # ---- ONE-SHOT MODE ----
            new_urls = [u for u in target_urls if u not in scraped_urls]
            if new_urls:
                print(f"[runner] {len(new_urls)} URLs to scrape ({len(scraped_urls)} already done)")
                scrape_batch(new_urls)
            else:
                print(f"[runner] All {len(target_urls)} URLs already scraped. Nothing to do.")

        # Final S3 upload
        if args.s3_bucket:
            upload_to_s3(str(jsonl_output), args.s3_bucket, jsonl_output.name)

        # Convert JSONL to JSON
        try:
            results = []
            with open(jsonl_output, "r", encoding="utf-8") as f_in:
                for line in f_in:
                    if line.strip():
                        results.append(json.loads(line))
            output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[runner] Converted {len(results)} items from JSONL to final JSON at {output_file.resolve()}")
            if args.s3_bucket:
                upload_to_s3(str(output_file), args.s3_bucket, output_file.name)
        except Exception as e:
            print(f"Error converting JSONL to JSON: {e}")


if __name__ == "__main__":
    main()
