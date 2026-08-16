"""
DearDariaCo Instagram auto-poster.

Mirrors pinterest_bot/generate_and_post_v2.py, but posts single-image feed
posts to Instagram via the Instagram API with Instagram Login (Content
Publishing) instead of pins. This flow does not require a linked Facebook
Page - only that the Instagram account itself is a Business or Creator
account, authorized directly through Instagram's own OAuth.

Content source: images live in images_instagram/, named
  <suite-slug>_<product_type>_<numeric-id>_<photo-index>.jpg
Each (<suite-slug>_<product_type>, <numeric-id>) group is one postable unit
(one product's photo set). The group's suite + product_type is looked up by
matching its filename prefix against pinterest_bot/content_bank_v2.json,
since that file already has the theme words, titles, and hashtags for every
suite/product_type combination. Captions are generated from that pooled
data rather than tied to one specific Etsy listing, because Instagram feed
captions don't support clickable links anyway (unlike Pinterest pins).

Environment variables:
  IG_ACCESS_TOKEN   Long-lived Instagram User access token (from Instagram
                     Login, scopes instagram_business_basic +
                     instagram_business_content_publish)
  IG_USER_ID        Instagram user_id returned by GET graph.instagram.com/me
                     (not the @handle)
  IMAGE_BASE_URL    Public base URL where images_instagram/ is served from
                     (e.g. https://raw.githubusercontent.com/<owner>/<repo>/main/images_instagram)
  POSTS_PER_RUN     How many posts to publish this run (default 1)
  DRY_RUN           "1" to print payloads instead of calling the API
"""

import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent
CONTENT_BANK_PATH = REPO_ROOT / "pinterest_bot" / "content_bank_v2.json"
IMAGES_DIR = REPO_ROOT / "images_instagram"
LOG_PATH = BASE_DIR / "posted_log.json"

GRAPH_API_BASE = "https://graph.instagram.com/v21.0"

POSTS_PER_RUN = int(os.environ.get("POSTS_PER_RUN", "1"))
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")

RECENT_CUTOFF_DAYS = 7
CONTAINER_POLL_ATTEMPTS = 10
CONTAINER_POLL_DELAY_SECS = 3

BANNED_PHRASES = ["hand-drawn", "—"]  # same house rules as the Pinterest bot

PRODUCT_TYPE_PHRASES = {
    "bundle": "a full matching wedding stationery suite",
    "sleeve": "an invitation sleeve",
    "place_card": "a place card",
    "rsvp": "an RSVP card",
    "save_the_date": "a save the date card",
    "menu": "a menu card",
    "glass_tag": "a wine glass tag",
    "other": "a wedding stationery piece",
}

DESCRIPTION_TEMPLATES = [
    "This {theme_word} {suite_name} design is {product_phrase}, made for Cricut Print Then Cut. Just download, print, and cut at home.",
    "A {theme_word} {suite_name} piece for your wedding stationery lineup. This is {product_phrase}, ready for Cricut Print Then Cut.",
    "Planning a {theme_word} wedding? This {suite_name} piece is {product_phrase} for Cricut Print Then Cut, easy to customize at home.",
    "Say hello to your new favorite {suite_name} design. {theme_word_cap} details throughout, built for Cricut Print Then Cut.",
    "This {suite_name} piece brings {theme_word} style to your wedding stationery. Made for Cricut Print Then Cut and easy to personalize.",
]

SHOP_CTA = "Shop this design (and the rest of the suite) at our Etsy shop, link in bio."

FILENAME_RE = re.compile(r"^(.*)_(\d+)_(\d+)\.(jpg|jpeg|png)$", re.IGNORECASE)


def load_json(path, default):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def clean_text(text):
    for phrase in BANNED_PHRASES:
        if phrase in text:
            raise ValueError(f"Generated text contains banned phrase '{phrase}': {text}")
    return text


def build_prefix_map(content_bank):
    """prefix (e.g. 'calla_lily_menu') -> list of (suite_id, suite, item)."""
    prefix_map = {}
    for suite_id, suite in content_bank["suites"].items():
        for item in suite["items"]:
            images = item.get("images") or []
            if not images:
                continue
            m = FILENAME_RE.match(images[0])
            if not m:
                continue
            prefix = m.group(1)
            prefix_map.setdefault(prefix, []).append((suite_id, suite, item))
    return prefix_map


def build_image_groups():
    """(prefix, numeric_id) -> sorted list of filenames, from images_instagram/."""
    groups = {}
    for fname in os.listdir(IMAGES_DIR):
        m = FILENAME_RE.match(fname)
        if not m:
            continue
        prefix, numid, idx, _ext = m.groups()
        groups.setdefault((prefix, numid), []).append((int(idx), fname))
    return {key: [f for _, f in sorted(files)] for key, files in groups.items()}


def build_pool(content_bank, log):
    now = datetime.now(timezone.utc)
    recent_keys = set()
    for entry in log.get("history", []):
        posted_at = datetime.fromisoformat(entry["posted_at"])
        if (now - posted_at).days < RECENT_CUTOFF_DAYS:
            recent_keys.add(entry["group_key"])

    prefix_map = build_prefix_map(content_bank)
    image_groups = build_image_groups()

    pool = []
    for (prefix, numid), images in image_groups.items():
        candidates = prefix_map.get(prefix)
        if not candidates:
            continue  # no matching catalog entry (e.g. bonus "showpiece" shots) - skip safely
        group_key = f"{prefix}::{numid}"
        if group_key in recent_keys:
            continue
        pool.append({"group_key": group_key, "images": images, "candidates": candidates})
    return pool


def generate_caption(entry, log):
    suite_id, suite, item = random.choice(entry["candidates"])
    theme_word = random.choice(suite["theme_words"])
    product_phrase = PRODUCT_TYPE_PHRASES.get(item["product_type"], PRODUCT_TYPE_PHRASES["other"])

    desc_idx = log.get("next_desc_template_idx", 0) % len(DESCRIPTION_TEMPLATES)
    description = DESCRIPTION_TEMPLATES[desc_idx].format(
        suite_name=suite["display_name"],
        theme_word=theme_word,
        theme_word_cap=theme_word.capitalize(),
        product_phrase=product_phrase,
    )
    log["next_desc_template_idx"] = desc_idx + 1

    # pool hashtags across every catalog item that shares this suite + product_type
    hashtag_pool = []
    for _sid, _suite, cand_item in entry["candidates"]:
        hashtag_pool.extend(cand_item.get("hashtags", []))
    hashtag_pool = list(dict.fromkeys(hashtag_pool))  # dedupe, keep order
    random.shuffle(hashtag_pool)
    hashtag_line = " ".join(hashtag_pool[:10])

    caption = clean_text(f"{description}\n\n{SHOP_CTA}\n\n{hashtag_line}")
    return caption, suite["display_name"], item["product_type"]


def create_media_container(image_url, caption):
    payload = {"image_url": image_url, "caption": caption, "access_token": ACCESS_TOKEN}
    resp = requests.post(f"{GRAPH_API_BASE}/{IG_USER_ID}/media", data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_container(container_id):
    for _ in range(CONTAINER_POLL_ATTEMPTS):
        resp = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": ACCESS_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Media container {container_id} failed to process")
        time.sleep(CONTAINER_POLL_DELAY_SECS)
    raise TimeoutError(f"Media container {container_id} did not finish processing in time")


def publish_container(container_id):
    payload = {"creation_id": container_id, "access_token": ACCESS_TOKEN}
    resp = requests.post(f"{GRAPH_API_BASE}/{IG_USER_ID}/media_publish", data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def post_entry(entry, caption):
    chosen_image = random.choice(entry["images"])
    image_url = f"{IMAGE_BASE_URL}/{chosen_image}"

    if DRY_RUN or not ACCESS_TOKEN or not IG_USER_ID:
        print("---- DRY RUN (no post actually published) ----")
        print(json.dumps({"image_url": image_url, "caption": caption}, indent=2))
        return "dry_run"

    container_id = create_media_container(image_url, caption)
    wait_for_container(container_id)
    return publish_container(container_id)


def main():
    content_bank = load_json(CONTENT_BANK_PATH, {"suites": {}})
    log = load_json(LOG_PATH, {"history": [], "next_desc_template_idx": 0})

    pool = build_pool(content_bank, log)
    if not pool:
        print("No eligible items to post (everything posted recently, or no images_instagram/ matches).")
        return

    random.shuffle(pool)
    todays_posts = pool[:POSTS_PER_RUN]

    for entry in todays_posts:
        caption, suite_name, product_type = generate_caption(entry, log)
        result = post_entry(entry, caption)

        log.setdefault("history", []).append({
            "group_key": entry["group_key"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        })
        save_json(LOG_PATH, log)

        print(f"Posted: {suite_name} / {product_type} ({entry['group_key']}) -> {result}")
        time.sleep(2)


if __name__ == "__main__":
    main()
