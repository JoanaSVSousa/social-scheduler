from dataclasses import dataclass
from typing import Optional


PLATFORMS = ["Instagram", "Facebook", "LinkedIn", "X", "Threads", "Bluesky", "YouTube Shorts", "TikTok"]
STATUSES = ["Draft", "Scheduled", "Published", "Failed"]

PLATFORM_CONTENT_LIMITS = {
    "Instagram": 2200,
    "Facebook": 63206,
    "LinkedIn": 3000,
    "X": 280,
    "Threads": 500,
    "Bluesky": 300,
    "YouTube Shorts": 100,
    "TikTok": 2200,
}

PLATFORM_MEDIA_GUIDES = {
    "Instagram": "Feed images, carousels, reels, videos, and stories. Use 9:16 video for Reels/Stories.",
    "Facebook": "Images, link previews, reels, and video. Landscape or square formats work well.",
    "LinkedIn": "Professional images, documents, and short videos. Prefer clear 1200x627 or square visuals.",
    "X": "Text-first posts, threads, images, video, and link commentary. Keep the opening line strong.",
    "Threads": "Images and short videos. Keep visuals simple and text-light.",
    "Bluesky": "Text-first posts, threads, images, and lightweight video. Keep media clear and alt-friendly.",
    "YouTube Shorts": "Vertical 9:16 video. Use MP4 when possible.",
    "TikTok": "Vertical 9:16 video. Short MP4 clips are the main format.",
}

PLATFORM_CONTENT_FORMATS = {
    "Instagram": ["Feed Post", "Carousel", "Reel", "Story", "Video Post"],
    "Facebook": ["Feed Post", "Story", "Reel", "Event Promo", "Video Post"],
    "LinkedIn": ["Text Post", "Image Post", "Video Post", "Document Post", "Article Share"],
    "X": ["Text Post", "Thread", "Image Post", "Video Post", "Link Commentary"],
    "Threads": ["Text Post", "Thread", "Image Post", "Video Post"],
    "Bluesky": ["Text Post", "Thread", "Image Post", "Video Post"],
    "YouTube Shorts": ["Short"],
    "TikTok": ["Video Post", "Story"],
}

FORMAT_MEDIA_GUIDES = {
    "Instagram": {
        "Feed Post": "Use square 1:1 or portrait 4:5 images/videos. Good for polished visuals.",
        "Carousel": "Attach multiple images/videos in sequence. Keep the first slide strong.",
        "Reel": "Use vertical 9:16 video. Short, direct, and motion-led.",
        "Story": "Use vertical 9:16 image or video. Designed for temporary, quick updates.",
        "Video Post": "Use MP4/MOV. Square, portrait, or vertical video works depending on goal.",
    },
    "Bluesky": {
        "Text Post": "Media optional. Keep the message concise and clear.",
        "Thread": "Use when the idea needs multiple connected posts. Media can support the first post.",
        "Image Post": "Attach clear images and write alt-friendly copy.",
        "Video Post": "Use lightweight video when motion adds context.",
    },
    "X": {
        "Text Post": "Use for quick updates, opinions, and short announcements.",
        "Thread": "Use when the idea needs multiple connected posts or a step-by-step explanation.",
        "Image Post": "Attach one or more clear images when the visual carries the message.",
        "Video Post": "Use short video clips when motion or screen recording adds value.",
        "Link Commentary": "Use when sharing an article or RSS item with your own angle before the link.",
    },
}

FORMAT_MEDIA_RULES = {
    "Story": {
        "media_required": True,
        "allowed_media_types": ["image", "video"],
        "layout": "Vertical full-screen media. Keep text out of the asset when possible.",
        "copy_guidance": "Story copy is mostly internal/editorial; the published asset carries the message.",
    },
    "Reel": {
        "media_required": True,
        "allowed_media_types": ["video"],
        "layout": "Vertical 9:16 video.",
        "copy_guidance": "Caption text is supported.",
    },
    "Short": {
        "media_required": True,
        "allowed_media_types": ["video"],
        "layout": "Vertical 9:16 video.",
        "copy_guidance": "Caption/description text is supported.",
    },
    "Video Post": {
        "media_required": True,
        "allowed_media_types": ["video"],
        "layout": "Video-first post.",
        "copy_guidance": "Caption text is supported.",
    },
    "Image Post": {
        "media_required": True,
        "allowed_media_types": ["image"],
        "layout": "Image-first post.",
        "copy_guidance": "Caption text is supported.",
    },
    "Carousel": {
        "media_required": True,
        "allowed_media_types": ["image", "video"],
        "layout": "Multiple media items.",
        "copy_guidance": "Caption text is supported.",
    },
    "Text Post": {
        "media_required": False,
        "allowed_media_types": [],
        "layout": "Text-only post.",
        "copy_guidance": "Media is hidden in preview for this format.",
    },
    "Thread": {
        "media_required": False,
        "allowed_media_types": ["image", "video"],
        "layout": "Text-first multi-post format.",
        "copy_guidance": "Media can support the first post.",
    },
}


def default_content_format(platform):
    return PLATFORM_CONTENT_FORMATS.get(platform, ["Post"])[0]


def content_character_limit(platform):
    return PLATFORM_CONTENT_LIMITS.get(platform, 2200)


def content_limit_for_post(platform, hashtags=""):
    limit = content_character_limit(platform)
    hashtags = (hashtags or "").strip()
    if hashtags:
        limit -= len(hashtags) + 2
    return max(limit, 1)


def truncate_content_for_platform(platform, content, hashtags=""):
    content = (content or "").strip()
    limit = content_limit_for_post(platform, hashtags)
    if len(content) <= limit:
        return content
    return content[:limit].rstrip()


@dataclass
class Post:
    title: str
    content: str
    hashtags: str
    platform: str
    content_format: str
    scheduled_at: str
    status: str
    rss_item_id: Optional[int] = None
    source_type: str = "Regular"
