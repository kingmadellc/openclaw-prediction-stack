#!/usr/bin/env python3
"""
X (Twitter) posting script for the OpenClaw Social Poster skill.
Reads credentials from ~/.openclaw/x-credentials.yaml and posts to @KingMadeLLC.

Usage:
    # Single post
    python3 x_post.py "my model says recession probability is 52%. kalshi has it at 35¢."

    # Thread (multiple args = thread posts)
    python3 x_post.py "thread post 1" "thread post 2" "thread post 3"

    # Dry run (prints what would post, doesn't actually post)
    python3 x_post.py --dry-run "test post content"

    # Post from file (one post per paragraph, separated by blank lines)
    python3 x_post.py --from-file ~/scans/latest_post.txt
"""

import sys
import os
import yaml
import tweepy
import time
import json
from pathlib import Path
from datetime import datetime


def load_credentials():
    """Load X API credentials from ~/.openclaw/x-credentials.yaml"""
    cred_paths = [
        Path.home() / ".openclaw" / "x-credentials.yaml",
        Path.home() / ".openclaw" / "x-credentials.yml",
        # Workspace path (for sandbox environments)
        Path(__file__).resolve().parents[3] / ".openclaw" / "x-credentials.yaml",
        Path("/Users/clawdkesselring/.openclaw/x-credentials.yaml"),
    ]
    for p in cred_paths:
        if p.exists():
            with open(p) as f:
                creds = yaml.safe_load(f)
            required = ["consumer_key", "consumer_secret", "access_token", "access_token_secret"]
            missing = [k for k in required if k not in creds or not creds[k]]
            if missing:
                print(f"ERROR: Missing keys in {p}: {missing}", file=sys.stderr)
                sys.exit(1)
            return creds
    print("ERROR: No credential file found. Expected ~/.openclaw/x-credentials.yaml", file=sys.stderr)
    sys.exit(1)


def get_client(creds):
    """Create authenticated tweepy Client for v2 API"""
    client = tweepy.Client(
        consumer_key=creds["consumer_key"],
        consumer_secret=creds["consumer_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
    )
    return client


def post_single(client, text, dry_run=False):
    """Post a single tweet. Returns tweet ID."""
    if len(text) > 280:
        print(f"WARNING: Post is {len(text)} chars (max 280). Truncating.", file=sys.stderr)
        text = text[:277] + "..."

    if dry_run:
        print(f"[DRY RUN] Would post: {text}")
        return "dry-run-id"

    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        print(f"POSTED: https://x.com/KingMadeLLC/status/{tweet_id}")
        return tweet_id
    except tweepy.errors.Forbidden as e:
        print(f"ERROR (403 Forbidden): {e}", file=sys.stderr)
        print("This usually means your Access Token has Read-only permissions.", file=sys.stderr)
        print("Fix: Go to developer.x.com → App → User Auth Settings → set Read+Write → regenerate Access Token.", file=sys.stderr)
        sys.exit(1)
    except tweepy.errors.TooManyRequests as e:
        print(f"ERROR (429 Rate Limited): {e}", file=sys.stderr)
        print("Free tier: 1,500 posts/month. Wait and retry.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def post_thread(client, posts, dry_run=False, delay_seconds=5):
    """Post a thread (list of posts). Each reply chains to the previous."""
    if not posts:
        print("ERROR: No posts to thread.", file=sys.stderr)
        sys.exit(1)

    tweet_ids = []

    # First post — no reply
    first_id = post_single(client, posts[0], dry_run=dry_run)
    tweet_ids.append(first_id)

    # Subsequent posts — reply to previous
    for i, text in enumerate(posts[1:], start=2):
        if not dry_run:
            time.sleep(delay_seconds)  # avoid rate limits

        if len(text) > 280:
            print(f"WARNING: Thread post {i} is {len(text)} chars. Truncating.", file=sys.stderr)
            text = text[:277] + "..."

        if dry_run:
            print(f"[DRY RUN] Would reply ({i}/{len(posts)}): {text}")
            tweet_ids.append("dry-run-id")
        else:
            try:
                response = client.create_tweet(
                    text=text,
                    in_reply_to_tweet_id=tweet_ids[-1]
                )
                tid = response.data["id"]
                print(f"THREAD {i}/{len(posts)}: https://x.com/KingMadeLLC/status/{tid}")
                tweet_ids.append(tid)
            except Exception as e:
                print(f"ERROR on thread post {i}: {e}", file=sys.stderr)
                print(f"Thread broken at post {i}. {i-1} posts succeeded.", file=sys.stderr)
                break

    return tweet_ids


def log_post(text, tweet_id, is_thread=False, thread_index=None):
    """Append post to local log for resolution tracking"""
    log_dir = Path.home() / "social-poster"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "post_log.jsonl"

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "tweet_id": str(tweet_id),
        "text": text,
        "is_thread": is_thread,
        "thread_index": thread_index,
        "url": f"https://x.com/KingMadeLLC/status/{tweet_id}" if tweet_id != "dry-run-id" else None,
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_posts_from_file(filepath):
    """Read posts from a text file. Paragraphs separated by blank lines."""
    with open(filepath) as f:
        content = f.read()
    # Split on double newlines (paragraph breaks)
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    return paragraphs


def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    dry_run = "--dry-run" in args
    from_file = "--from-file" in args

    # Remove flags from args
    args = [a for a in args if a not in ("--dry-run", "--from-file")]

    if from_file:
        if not args:
            print("ERROR: --from-file requires a filepath argument", file=sys.stderr)
            sys.exit(1)
        posts = read_posts_from_file(args[0])
    else:
        posts = args

    if not posts:
        print("ERROR: No content to post.", file=sys.stderr)
        sys.exit(1)

    creds = load_credentials()
    client = get_client(creds)

    if len(posts) == 1:
        # Single post
        tweet_id = post_single(client, posts[0], dry_run=dry_run)
        log_post(posts[0], tweet_id)
    else:
        # Thread
        tweet_ids = post_thread(client, posts, dry_run=dry_run)
        for i, (text, tid) in enumerate(zip(posts, tweet_ids)):
            log_post(text, tid, is_thread=True, thread_index=i)

    if not dry_run:
        print(f"\nLogged to ~/social-poster/post_log.jsonl")


if __name__ == "__main__":
    main()
