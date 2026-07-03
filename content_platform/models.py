from dataclasses import dataclass
from typing import Optional


PLATFORMS = ["Instagram", "Facebook", "LinkedIn", "X", "Threads", "Bluesky", "YouTube Shorts", "TikTok"]
STATUSES = ["Draft", "Scheduled", "Published", "Failed"]

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


def default_content_format(platform):
    return PLATFORM_CONTENT_FORMATS.get(platform, ["Post"])[0]


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
