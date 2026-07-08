import re

from ..models import truncate_content_for_platform


URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
HASHTAG_PATTERN = re.compile(r"(?<!\S)#([^\d\s][^\s]*)", re.UNICODE)
TRAILING_FACET_PUNCTUATION = ".,;:!?)]}"


def compose_publication_text(platform, content, hashtags):
    """Build the final outgoing caption consistently for every social platform."""
    hashtags = (hashtags or "").strip()
    content = truncate_content_for_platform(platform, content, hashtags)
    return "\n\n".join(piece for piece in [content, hashtags] if piece)


def detect_social_entities(text):
    """Extract links and hashtags once so every publisher can share the same parsing rules."""
    text = text or ""
    entities = []
    occupied_ranges = []

    for match in URL_PATTERN.finditer(text):
        value = _trim_entity_value(match.group(0))
        if not value:
            continue
        start = match.start()
        end = start + len(value)
        entities.append({"type": "link", "start": start, "end": end, "value": value})
        occupied_ranges.append((start, end))

    for match in HASHTAG_PATTERN.finditer(text):
        value = _trim_entity_value(match.group(0))
        if len(value) <= 1:
            continue
        start = match.start()
        end = start + len(value)
        if _overlaps_existing_entity(start, end, occupied_ranges):
            continue
        entities.append({"type": "hashtag", "start": start, "end": end, "value": value[1:]})

    return sorted(entities, key=lambda entity: entity["start"])


def utf8_byte_range(text, start, end):
    """Social APIs often index rich text by UTF-8 bytes, not Python character positions."""
    return {
        "byteStart": len(text[:start].encode("utf-8")),
        "byteEnd": len(text[:end].encode("utf-8")),
    }


def _trim_entity_value(value):
    return value.rstrip(TRAILING_FACET_PUNCTUATION)


def _overlaps_existing_entity(start, end, ranges):
    return any(max(start, range_start) < min(end, range_end) for range_start, range_end in ranges)
