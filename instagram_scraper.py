#!/usr/bin/env python3
"""Export public Instagram profile and post metadata for analysis.

This script uses Instaloader's normal Instagram access path. It does not bypass
private profiles, paywalls, login challenges, or rate limits. Use it only for
accounts and data you are authorized to collect.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

try:
    import instaloader
    from instaloader import (
        ConnectionException,
        Instaloader,
        LoginException,
        LoginRequiredException,
        Profile,
        ProfileNotExistsException,
        Post,
        QueryReturnedForbiddenException,
        TooManyRequestsException,
    )
except ImportError:  # pragma: no cover - handled at runtime for friendlier CLI output
    instaloader = None  # type: ignore[assignment]
    ConnectionException = Exception  # type: ignore[assignment,misc]
    LoginException = Exception  # type: ignore[assignment,misc]
    LoginRequiredException = Exception  # type: ignore[assignment,misc]
    Instaloader = object  # type: ignore[assignment,misc]
    Profile = object  # type: ignore[assignment,misc]
    ProfileNotExistsException = Exception  # type: ignore[assignment,misc]
    Post = object  # type: ignore[assignment,misc]
    QueryReturnedForbiddenException = Exception  # type: ignore[assignment,misc]
    TooManyRequestsException = Exception  # type: ignore[assignment,misc]


@dataclass
class CommentRecord:
    id: int | None
    owner_username: str | None
    text: str
    created_at_utc: str | None
    likes_count: int | None


@dataclass
class PostRecord:
    shortcode: str
    url: str
    date_utc: str
    typename: str
    is_video: bool
    caption: str | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None
    photo_url: str | None
    video_url: str | None
    media_urls: list[str]
    comments: list[CommentRecord]


@dataclass
class ProfileRecord:
    username: str
    full_name: str
    biography: str
    external_url: str | None
    follower_count: int
    following_count: int
    media_count: int
    is_private: bool
    is_verified: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Instagram profile metadata, posts, media URLs, and comments."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        help="Instagram profile URL, @username, or username to export.",
    )
    parser.add_argument(
        "--output",
        default="output/instagram_export.json",
        help="Path for the JSON export. Default: output/instagram_export.json",
    )
    parser.add_argument(
        "--csv-output",
        default=None,
        help="Optional CSV path for a flattened post export.",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Maximum posts to export. Omit to export all accessible posts.",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=100,
        help="Maximum comments to export per post. Use 0 to skip comments. Default: 100",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to sleep between posts to reduce request pressure. Default: 1.0",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Login using IG_USERNAME/IG_PASSWORD, or an existing Instaloader session.",
    )
    parser.add_argument(
        "--session-user",
        default=None,
        help="Load an existing Instaloader session for this username before password login.",
    )
    return parser.parse_args()


def parse_profile_input(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise SystemExit("Provide an Instagram profile URL, @username, or username.")

    if "://" in raw_value or raw_value.startswith("www."):
        normalized_url = raw_value if "://" in raw_value else f"https://{raw_value}"
        parsed = urlparse(normalized_url)
        host = parsed.netloc.lower()
        if host not in {"instagram.com", "www.instagram.com"}:
            raise SystemExit(f"Expected an instagram.com profile URL, got: {raw_value}")

        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            raise SystemExit(f"Profile URL does not contain a username: {raw_value}")

        reserved_paths = {
            "p",
            "reel",
            "reels",
            "stories",
            "explore",
            "accounts",
            "direct",
        }
        if path_parts[0].lower() in reserved_paths:
            raise SystemExit(
                "This script expects a profile URL, not a post, reel, story, or Instagram app URL. "
                "Use a URL like https://www.instagram.com/nasa/."
            )
        return path_parts[0].lstrip("@")

    return raw_value.lstrip("@").rstrip("/")


def get_profile_input(args: argparse.Namespace) -> str:
    if args.profile:
        return args.profile

    try:
        return input("Instagram profile link, @username, or username: ")
    except EOFError as exc:
        raise SystemExit("No profile input provided.") from exc


def require_instaloader() -> None:
    if instaloader is None:
        raise SystemExit(
            "Missing dependency: instaloader. Install it with:\n"
            "  python3 -m pip install -r requirements.txt"
        )


def make_loader() -> Instaloader:
    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )


def load_saved_session(loader: Instaloader, session_user: str) -> bool:
    try:
        loader.load_session_from_file(session_user)
    except FileNotFoundError:
        return False
    print(f"Loaded Instaloader session for {session_user}", file=sys.stderr)
    return True


def login_if_requested(loader: Instaloader, args: argparse.Namespace) -> None:
    if not args.login and not args.session_user:
        return

    session_user = args.session_user or os.getenv("IG_USERNAME")
    if session_user:
        if load_saved_session(loader, session_user):
            return
        if args.session_user and not args.login:
            raise SystemExit(
                f"No saved Instaloader session found for {args.session_user}. "
                "Run `.venv/bin/instaloader --login YOUR_USERNAME` first, "
                "or provide IG_USERNAME/IG_PASSWORD."
            )

    username = os.getenv("IG_USERNAME")
    password = os.getenv("IG_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "--login requires IG_USERNAME and IG_PASSWORD env vars, or a saved session via --session-user."
        )
    loader.login(username, password)
    print(f"Logged in as {username}", file=sys.stderr)


def prompt_for_saved_session(loader: Instaloader) -> bool:
    if not sys.stdin.isatty():
        return False

    print(
        "\nInstagram blocked anonymous profile access or returned a misleading "
        "'profile does not exist' response.",
        file=sys.stderr,
    )
    session_user = input(
        "Enter your Instagram username for a saved Instaloader session, "
        "or press Enter to stop: "
    ).strip()
    if not session_user:
        return False

    if load_saved_session(loader, session_user):
        return True

    raise SystemExit(
        f"No saved Instaloader session found for {session_user}.\n"
        f"Create one first with:\n"
        f"  .venv/bin/instaloader --login {session_user}\n"
        f"Then rerun this script with:\n"
        f"  .venv/bin/python instagram_scraper.py --session-user {session_user} "
        f"--max-posts 25 --max-comments 50"
    )


def get_profile(loader: Instaloader, username: str) -> Profile:
    try:
        return Profile.from_username(loader.context, username)
    except ProfileNotExistsException as exc:
        if not loader.context.is_logged_in and prompt_for_saved_session(loader):
            return Profile.from_username(loader.context, username)
        raise SystemExit(
            f"Could not load @{username}.\n"
            "Instagram may have blocked anonymous scraping, or the username may be unavailable. "
            "If the account exists, create/use a saved login session:\n"
            f"  .venv/bin/instaloader --login YOUR_INSTAGRAM_USERNAME\n"
            f"  .venv/bin/python instagram_scraper.py --session-user YOUR_INSTAGRAM_USERNAME "
            f"--max-posts 25 --max-comments 50"
        ) from exc
    except QueryReturnedForbiddenException as exc:
        if not loader.context.is_logged_in and prompt_for_saved_session(loader):
            return Profile.from_username(loader.context, username)
        raise SystemExit(
            f"Instagram returned 403 Forbidden while loading @{username}.\n"
            "That usually means anonymous access is blocked. Use a saved session:\n"
            f"  .venv/bin/instaloader --login YOUR_INSTAGRAM_USERNAME\n"
            f"  .venv/bin/python instagram_scraper.py --session-user YOUR_INSTAGRAM_USERNAME "
            f"--max-posts 25 --max-comments 50"
        ) from exc
    except ConnectionException as exc:
        message = str(exc)
        if "403 Forbidden" in message and not loader.context.is_logged_in and prompt_for_saved_session(loader):
            return Profile.from_username(loader.context, username)
        if "403 Forbidden" in message:
            raise SystemExit(
                f"Instagram returned 403 Forbidden while loading @{username}.\n"
                "That usually means Instagram blocked the request. Use a saved session:\n"
                f"  .venv/bin/instaloader --login YOUR_INSTAGRAM_USERNAME\n"
                f"  .venv/bin/python instagram_scraper.py --session-user YOUR_INSTAGRAM_USERNAME "
                f"--max-posts 25 --max-comments 50"
            ) from exc
        raise SystemExit(
            f"Could not reach Instagram while loading @{username}.\n"
            f"Details: {message}\n"
            "Check your network connection, then retry. If Instagram blocks anonymous access, "
            "use --session-user with a saved Instaloader session."
        ) from exc
    except TooManyRequestsException as exc:
        raise SystemExit(
            "Instagram rate limited the requests. Wait before retrying, and use "
            "--session-user plus a higher --sleep value for larger exports."
        ) from exc
    except LoginException as exc:
        raise SystemExit(f"Instagram login/session failed: {exc}") from exc


def collect_media_urls(post: Post) -> list[str]:
    urls: list[str] = []
    if post.typename == "GraphSidecar":
        try:
            for node in post.get_sidecar_nodes():
                if node.display_url:
                    urls.append(str(node.display_url))
                elif node.video_url:
                    urls.append(str(node.video_url))
        except Exception as exc:  # noqa: BLE001 - keep export moving when one carousel fails
            print(f"Warning: could not read carousel media for {post.shortcode}: {exc}", file=sys.stderr)
    elif post.url:
        urls.append(str(post.url))
    return urls


def collect_comments(post: Post, max_comments: int) -> list[CommentRecord]:
    if max_comments <= 0:
        return []

    comments: list[CommentRecord] = []
    try:
        for comment in post.get_comments():
            comments.append(
                CommentRecord(
                    id=getattr(comment, "id", None),
                    owner_username=getattr(comment.owner, "username", None),
                    text=comment.text,
                    created_at_utc=comment.created_at_utc.isoformat()
                    if getattr(comment, "created_at_utc", None)
                    else None,
                    likes_count=getattr(comment, "likes_count", None),
                )
            )
            if len(comments) >= max_comments:
                break
    except LoginRequiredException:
        print(
            f"Warning: comments for {post.shortcode} require login or are not accessible.",
            file=sys.stderr,
        )
    except ConnectionException as exc:
        print(f"Warning: connection error reading comments for {post.shortcode}: {exc}", file=sys.stderr)
    return comments


def profile_to_record(profile: Profile) -> ProfileRecord:
    return ProfileRecord(
        username=profile.username,
        full_name=profile.full_name,
        biography=profile.biography,
        external_url=profile.external_url,
        follower_count=profile.followers,
        following_count=profile.followees,
        media_count=profile.mediacount,
        is_private=profile.is_private,
        is_verified=profile.is_verified,
    )


def post_to_record(post: Post, max_comments: int) -> PostRecord:
    media_urls = collect_media_urls(post)
    photo_url = str(post.url) if post.url else (media_urls[0] if media_urls else None)
    video_url = str(post.video_url) if post.is_video and post.video_url else None
    return PostRecord(
        shortcode=post.shortcode,
        url=f"https://www.instagram.com/p/{post.shortcode}/",
        date_utc=post.date_utc.isoformat(),
        typename=post.typename,
        is_video=post.is_video,
        caption=post.caption,
        like_count=post.likes,
        comment_count=post.comments,
        share_count=None,
        photo_url=photo_url,
        video_url=video_url,
        media_urls=media_urls,
        comments=collect_comments(post, max_comments=max_comments),
    )


def dataclass_to_jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [dataclass_to_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: dataclass_to_jsonable(item) for key, item in asdict(value).items()}
    return value


def write_json(path: Path, profile: ProfileRecord, posts: list[PostRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": dataclass_to_jsonable(profile),
        "posts": dataclass_to_jsonable(posts),
        "notes": {
            "share_count": "Instagram does not expose public per-post share counts through this access path, so this is null.",
            "comments": "Comments may be incomplete if Instagram requires login, rate limits requests, or comments exceed --max-comments.",
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, profile: ProfileRecord, posts: Iterable[PostRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "profile_username",
        "profile_followers",
        "profile_following",
        "profile_bio",
        "shortcode",
        "url",
        "date_utc",
        "typename",
        "is_video",
        "caption",
        "like_count",
        "comment_count",
        "share_count",
        "photo_url",
        "video_url",
        "media_urls_json",
        "comments_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for post in posts:
            writer.writerow(
                {
                    "profile_username": profile.username,
                    "profile_followers": profile.follower_count,
                    "profile_following": profile.following_count,
                    "profile_bio": profile.biography,
                    "shortcode": post.shortcode,
                    "url": post.url,
                    "date_utc": post.date_utc,
                    "typename": post.typename,
                    "is_video": post.is_video,
                    "caption": post.caption,
                    "like_count": post.like_count,
                    "comment_count": post.comment_count,
                    "share_count": post.share_count,
                    "photo_url": post.photo_url,
                    "video_url": post.video_url,
                    "media_urls_json": json.dumps(post.media_urls, ensure_ascii=False),
                    "comments_json": json.dumps(
                        [dataclass_to_jsonable(comment) for comment in post.comments],
                        ensure_ascii=False,
                    ),
                }
            )


def export_profile(args: argparse.Namespace) -> tuple[ProfileRecord, list[PostRecord]]:
    require_instaloader()
    loader = make_loader()
    login_if_requested(loader, args)

    username = parse_profile_input(get_profile_input(args))
    profile = get_profile(loader, username)
    profile_record = profile_to_record(profile)

    if profile.is_private and not profile.followed_by_viewer:
        raise SystemExit(
            f"@{username} is private and is not accessible to the current session. "
            "Use an authorized account that follows it, or choose a public profile."
        )

    posts: list[PostRecord] = []
    for index, post in enumerate(profile.get_posts(), start=1):
        if args.max_posts is not None and len(posts) >= args.max_posts:
            break
        print(f"Exporting post {index}: {post.shortcode}", file=sys.stderr)
        posts.append(post_to_record(post, max_comments=args.max_comments))
        if args.sleep > 0:
            time.sleep(args.sleep)

    return profile_record, posts


def main() -> int:
    args = parse_args()
    profile, posts = export_profile(args)
    write_json(Path(args.output), profile, posts)
    if args.csv_output:
        write_csv(Path(args.csv_output), profile, posts)

    print(
        f"Exported @{profile.username}: {len(posts)} posts to {args.output}"
        + (f" and {args.csv_output}" if args.csv_output else "")
    )
    if any(post.share_count is None for post in posts):
        print("Note: share_count is null because Instagram does not expose it publicly here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
