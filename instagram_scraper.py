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
from datetime import datetime, timezone
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
        if loader.context.is_logged_in:
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
        if not loader.context.is_logged_in and prompt_for_saved_session(loader):
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
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
        if loader.context.is_logged_in:
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
        if not loader.context.is_logged_in and prompt_for_saved_session(loader):
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
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
        if loader.context.is_logged_in:
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
        if "403 Forbidden" in message and not loader.context.is_logged_in and prompt_for_saved_session(loader):
            profile = get_profile_from_mobile_endpoint(loader, username)
            if profile:
                return profile
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


def get_profile_from_mobile_endpoint(loader: Instaloader, username: str) -> Profile | None:
    try:
        response = loader.context.get_iphone_json(
            "api/v1/users/web_profile_info/",
            {"username": username},
        )
    except ConnectionException as exc:
        print(f"Warning: mobile profile fallback failed for @{username}: {exc}", file=sys.stderr)
        return None

    user = response.get("data", {}).get("user")
    if not user:
        return None
    return Profile(loader.context, user)


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


def collect_mobile_media_urls(item: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
    media_urls: list[str] = []
    photo_url: str | None = None
    video_url: str | None = None

    def best_image_url(media: dict[str, Any]) -> str | None:
        candidates = media.get("image_versions2", {}).get("candidates", [])
        if not candidates:
            return media.get("display_uri")
        best = max(candidates, key=lambda candidate: candidate.get("width", 0) * candidate.get("height", 0))
        return best.get("url")

    def best_video_url(media: dict[str, Any]) -> str | None:
        versions = media.get("video_versions", [])
        if not versions:
            return None
        best = max(versions, key=lambda candidate: candidate.get("width", 0) * candidate.get("height", 0))
        return best.get("url")

    media_items = item.get("carousel_media") or [item]
    for media in media_items:
        image_url = best_image_url(media)
        if image_url:
            media_urls.append(image_url)
            if photo_url is None:
                photo_url = image_url

        candidate_video_url = best_video_url(media)
        if candidate_video_url:
            media_urls.append(candidate_video_url)
            if video_url is None:
                video_url = candidate_video_url

    return photo_url, video_url, media_urls


def collect_mobile_comments(
    loader: Instaloader,
    item: dict[str, Any],
    max_comments: int,
    comment_state: dict[str, bool],
) -> list[CommentRecord]:
    if max_comments <= 0 or comment_state.get("disabled", False):
        return []

    media_id = str(item.get("id") or item.get("pk") or "")
    if not media_id:
        return []

    comments: list[CommentRecord] = []
    min_id: str | None = None
    while len(comments) < max_comments:
        params = {"can_support_threading": "true"}
        if min_id:
            params["min_id"] = min_id

        try:
            response = loader.context.get_iphone_json(f"api/v1/media/{media_id}/comments/", params)
        except ConnectionException as exc:
            print(
                f"Warning: comments unavailable for {item.get('code', media_id)}: {exc}. "
                "Skipping comments for the rest of this run.",
                file=sys.stderr,
            )
            comment_state["disabled"] = True
            return comments

        for comment in response.get("comments", []):
            created_at = comment.get("created_at_utc") or comment.get("created_at")
            comments.append(
                CommentRecord(
                    id=comment.get("pk"),
                    owner_username=comment.get("user", {}).get("username"),
                    text=comment.get("text", ""),
                    created_at_utc=datetime.fromtimestamp(created_at, timezone.utc).isoformat()
                    if created_at
                    else None,
                    likes_count=comment.get("comment_like_count") or comment.get("like_count"),
                )
            )
            if len(comments) >= max_comments:
                break

        min_id = response.get("next_min_id")
        if not min_id or not response.get("has_more_comments"):
            break

    return comments


def mobile_item_to_record(
    loader: Instaloader,
    item: dict[str, Any],
    max_comments: int,
    comment_state: dict[str, bool],
) -> PostRecord:
    photo_url, video_url, media_urls = collect_mobile_media_urls(item)
    caption = item.get("caption") or {}
    taken_at = item.get("taken_at")
    media_type = item.get("media_type")
    typename = {
        1: "GraphImage",
        2: "GraphVideo",
        8: "GraphSidecar",
    }.get(media_type, str(media_type or "Unknown"))

    return PostRecord(
        shortcode=item.get("code", ""),
        url=f"https://www.instagram.com/p/{item.get('code', '')}/",
        date_utc=datetime.fromtimestamp(taken_at, timezone.utc).isoformat() if taken_at else "",
        typename=typename,
        is_video=media_type == 2 or bool(video_url),
        caption=caption.get("text") if isinstance(caption, dict) else None,
        like_count=item.get("like_count"),
        comment_count=item.get("comment_count"),
        share_count=item.get("share_count"),
        photo_url=photo_url,
        video_url=video_url,
        media_urls=media_urls,
        comments=collect_mobile_comments(
            loader,
            item,
            max_comments=max_comments,
            comment_state=comment_state,
        ),
    )


def collect_mobile_posts(
    loader: Instaloader,
    profile: Profile,
    max_posts: int | None,
    max_comments: int,
    sleep_seconds: float,
) -> list[PostRecord]:
    posts: list[PostRecord] = []
    max_id: str | None = None
    comment_state = {"disabled": False}

    while max_posts is None or len(posts) < max_posts:
        remaining = 12 if max_posts is None else max(1, min(12, max_posts - len(posts)))
        params = {"count": str(remaining)}
        if max_id:
            params["max_id"] = max_id

        try:
            response = loader.context.get_iphone_json(f"api/v1/feed/user/{profile.userid}/", params)
        except ConnectionException as exc:
            raise SystemExit(
                f"Could not load posts for @{profile.username} through Instagram's mobile feed endpoint.\n"
                f"Details: {exc}\n"
                "Wait a few minutes before retrying, or rerun with a larger --sleep value."
            ) from exc

        items = response.get("items", [])
        if not items:
            break

        for item in items:
            if max_posts is not None and len(posts) >= max_posts:
                break
            print(f"Exporting post {len(posts) + 1}: {item.get('code')}", file=sys.stderr)
            posts.append(
                mobile_item_to_record(
                    loader,
                    item,
                    max_comments=max_comments,
                    comment_state=comment_state,
                )
            )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        max_id = response.get("next_max_id")
        if not response.get("more_available") or not max_id:
            break

    return posts


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

    if loader.context.is_logged_in:
        posts = collect_mobile_posts(
            loader,
            profile,
            max_posts=args.max_posts,
            max_comments=args.max_comments,
            sleep_seconds=args.sleep,
        )
    else:
        posts = []
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
