# Instagram Profile Exporter

Exports accessible Instagram profile metadata and post data into JSON, with an optional flattened CSV for analysis.

Use this only for accounts and data you are authorized to collect. The script uses normal `instaloader` access and does not bypass private profiles, login challenges, rate limits, or unavailable metrics.

## What It Exports

- Profile username, full name, bio, external URL, follower count, following count, media count, verified/private flags
- Post shortcode, permalink, UTC date, media type, caption/description
- Post photo URL, video URL when present, and all carousel media URLs
- Like count and comment count
- Comments, including commenter username, text, timestamp, and comment like count
- `share_count` as `null`

Instagram does not expose public per-post share counts through this access path, so `share_count` is intentionally `null`. If your own Instagram data export contains share metrics, merge those later by shortcode or permalink.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Basic Usage

Export the latest 25 accessible posts from a profile link with up to 50 comments per post:

```bash
.venv/bin/python instagram_scraper.py "https://www.instagram.com/instagram/" --max-posts 25 --max-comments 50 --output output/instagram.json --csv-output output/instagram.csv
```

You can also pass `@instagram` or `instagram` instead of the full link.

Export all accessible posts from a profile link, skipping comments:

```bash
.venv/bin/python instagram_scraper.py "https://www.instagram.com/instagram/" --max-comments 0 --output output/instagram.json
```

## Login

Some metadata and comments require an authenticated Instagram session.

Recommended session flow:

```bash
.venv/bin/instaloader --login YOUR_INSTAGRAM_USERNAME
.venv/bin/python instagram_scraper.py "https://www.instagram.com/target_username/" --session-user YOUR_INSTAGRAM_USERNAME --max-posts 25
```

Environment-variable login also works:

```bash
export IG_USERNAME="your_username"
export IG_PASSWORD="your_password"
.venv/bin/python instagram_scraper.py "https://www.instagram.com/target_username/" --login --max-posts 25
```

The script will not access private profiles unless the logged-in account is already authorized to view them.

## Output Shape

The JSON output has this top-level structure:

```json
{
  "profile": {},
  "posts": [],
  "notes": {}
}
```

Each post includes a stable Instagram `shortcode`, which is usually the best join key when combining this export with your own Instagram data.

## Practical Limits

- Instagram may rate limit or challenge requests, especially for large exports.
- Comments can be slow and may require login.
- Public share counts are not available through this script.
- Media URLs are remote Instagram CDN URLs and may expire.
