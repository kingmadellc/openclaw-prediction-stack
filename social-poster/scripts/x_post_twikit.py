#!/usr/bin/env python3
"""
X (Twitter) posting via Twikit — no API key, no credits, no bullshit.
Uses your X session cookies to post directly.

First run:  python3 x_post_twikit.py --login
Then:       python3 x_post_twikit.py "your post content here"
Thread:     python3 x_post_twikit.py "post 1" "post 2" "post 3"
Dry run:    python3 x_post_twikit.py --dry-run "test content"
"""

import sys
import os
import json
import asyncio
import time
from pathlib import Path
from datetime import datetime

from twikit import Client

COOKIES_PATH = Path.home() / ".openclaw" / "x-cookies.json"
# Also check workspace path for sandbox environments
COOKIES_PATH_ALT = Path(__file__).resolve().parents[3] / ".openclaw" / "x-cookies.json"
COOKIES_PATH_MAC = Path("/Users/clawdkesselring/.openclaw/x-cookies.json")

LOG_DIR = Path.home() / "social-poster"
LOG_FILE = LOG_DIR / "post_log.jsonl"


def get_cookies_path():
    for p in [COOKIES_PATH, COOKIES_PATH_ALT, COOKIES_PATH_MAC]:
        if p.exists():
            return p
    # Default to first path for creation
    return COOKIES_PATH


async def login():
    """Interactive login — run once to save session cookies."""
    import getpass
    print("=== X Login (saves session cookies, only needed once) ===")
    username = input("X username (e.g. KingMadeLLC): ").strip()
    email = input("Email on the account: ").strip()
    password = getpass.getpass("Password: ")

    client = Client('en-US')
    await client.login(auth_info_1=username, auth_info_2=email, password=password)

    # Save cookies
    cookies_path = COOKIES_PATH
    cookies_path.parent.mkdir(parents=True, exist_ok=True)
    client.save_cookies(str(cookies_path))
    print(f"\nSession saved to {cookies_path}")
    print("You can now post without logging in again.")
    return client


async def load_client():
    """Load client from saved cookies."""
    cookies_path = get_cookies_path()
    if not cookies_path.exists():
        print("ERROR: No saved session. Run with --login first.", file=sys.stderr)
        print(f"  python3 {sys.argv[0]} --login", file=sys.stderr)
        sys.exit(1)

    client = Client('en-US')
    client.load_cookies(str(cookies_path))
    return client


async def post_single(client, text, dry_run=False):
    """Post a single tweet. Returns tweet ID."""
    if len(text) > 280:
        print(f"WARNING: Post is {len(text)} chars (max 280). Truncating.", file=sys.stderr)
        text = text[:277] + "..."

    if dry_run:
        print(f"[DRY RUN] Would post ({len(text)} chars):\n{text}")
        return "dry-run-id"

    try:
        tweet = await client.create_tweet(text=text)
        tweet_id = tweet.id
        print(f"POSTED: https://x.com/KingMadeLLC/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


async def post_thread(client, posts, dry_run=False, delay_seconds=3):
    """Post a thread. Each reply chains to the previous."""
    if not posts:
        print("ERROR: No posts to thread.", file=sys.stderr)
        sys.exit(1)

    tweet_ids = []

    # First post
    first_id = await post_single(client, posts[0], dry_run=dry_run)
    tweet_ids.append(first_id)

    # Replies
    for i, text in enumerate(posts[1:], start=2):
        if not dry_run:
            await asyncio.sleep(delay_seconds)

        if len(text) > 280:
            print(f"WARNING: Thread post {i} is {len(text)} chars. Truncating.", file=sys.stderr)
            text = text[:277] + "..."

        if dry_run:
            print(f"[DRY RUN] Would reply ({i}/{len(posts)}, {len(text)} chars):\n{text}")
            tweet_ids.append("dry-run-id")
        else:
            try:
                tweet = await client.create_tweet(text=text, reply_to=tweet_ids[-1])
                tid = tweet.id
                print(f"THREAD {i}/{len(posts)}: https://x.com/KingMadeLLC/status/{tid}")
                tweet_ids.append(tid)
            except Exception as e:
                print(f"ERROR on thread post {i}: {e}", file=sys.stderr)
                print(f"Thread broken at post {i}. {i-1} posts succeeded.", file=sys.stderr)
                break

    return tweet_ids


def log_post(text, tweet_id, is_thread=False, thread_index=None):
    """Append post to local log."""
    LOG_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "tweet_id": str(tweet_id),
        "text": text,
        "is_thread": is_thread,
        "thread_index": thread_index,
        "url": f"https://x.com/KingMadeLLC/status/{tweet_id}" if tweet_id != "dry-run-id" else None,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    if "--login" in args:
        await login()
        return

    dry_run = "--dry-run" in args
    args = [a for a in args if a not in ("--dry-run",)]

    if not args:
        print("ERROR: No content to post.", file=sys.stderr)
        sys.exit(1)

    client = await load_client()

    posts = args

    if len(posts) == 1:
        tweet_id = await post_single(client, posts[0], dry_run=dry_run)
        log_post(posts[0], tweet_id)
    else:
        tweet_ids = await post_thread(client, posts, dry_run=dry_run)
        for i, (text, tid) in enumerate(zip(posts, tweet_ids)):
            log_post(text, tid, is_thread=True, thread_index=i)

    if not dry_run:
        print(f"\nLogged to {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
