# instalytics

`instalytics` is a small Python utility for exporting Instagram profile and post information for a given user using your own Instagram account.

It was created for use in class `ITMG 494`.

The exporter writes accessible profile and post metadata to JSON, with an optional flattened CSV that is easier to combine with other data for analysis.

## What It Exports

- Profile username, full name, bio, external URL, follower count, following count, media count, verified/private flags
- Post shortcode, permalink, UTC date, media type, caption/description
- Post photo URL, video URL when present, and carousel media URLs
- Like count and comment count
- Comments when Instagram allows the comments endpoint for your account/session
- `share_count` as `null` when Instagram does not expose it

Use this only for accounts and data you are authorized to collect. The script uses normal `instaloader` access with your own account session. It does not bypass private profiles, login challenges, rate limits, or unavailable metrics.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

This repository does not include Instagram credentials, cookies, or session files. Each user creates their own local Instagram session.

## Create Your Instagram Session

```bash
.venv/bin/instaloader --login YOUR_INSTAGRAM_USERNAME
```

This prompts for your Instagram password and saves an Instaloader session under your user config directory, usually:

```text
~/.config/instaloader/session-YOUR_INSTAGRAM_USERNAME
```

That session is not saved in this project folder.

## Run The Exporter

Run the script, then paste the target Instagram profile link when prompted:

```bash
.venv/bin/python instagram_scraper.py --session-user YOUR_INSTAGRAM_USERNAME --max-posts 25 --max-comments 0 --output output/instagram.json --csv-output output/instagram.csv
```

At the prompt, enter a profile link like:

```text
https://www.instagram.com/instagram/
```

You can also enter `@instagram` or `instagram`.

You can request comments too:

```bash
.venv/bin/python instagram_scraper.py --session-user YOUR_INSTAGRAM_USERNAME --max-posts 25 --max-comments 50 --output output/instagram.json --csv-output output/instagram.csv
```

If Instagram rejects the comments endpoint, the export continues and leaves `comments` empty for affected posts. For class analysis, `--max-comments 0` is usually faster and more reliable if you only need post-level metrics.

## Output

The JSON output has this top-level structure:

```json
{
  "profile": {},
  "posts": [],
  "notes": {}
}
```

The CSV output has one row per post and repeats profile-level fields on each row so it can be opened directly in Excel, Google Sheets, Python, or R.

Each post includes a stable Instagram `shortcode`, which is usually the best join key when combining this export with your own Instagram data.

## Sharing This Project

Another person can use the repo by running:

```bash
git clone REPO_URL
cd instalytics
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/instaloader --login THEIR_INSTAGRAM_USERNAME
.venv/bin/python instagram_scraper.py --session-user THEIR_INSTAGRAM_USERNAME --max-posts 25 --max-comments 0 --output output/instagram.json --csv-output output/instagram.csv
```

They should use their own Instagram account and session.

## Practical Limits

- Instagram may rate limit, challenge, or block requests.
- Private profiles only work if your logged-in account can already view them.
- Comments may be unavailable even when post metadata works.
- Public per-post share counts are not reliably exposed through this access path.
- Media URLs are remote Instagram CDN URLs and may expire.
