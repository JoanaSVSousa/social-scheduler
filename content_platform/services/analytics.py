from collections import Counter


def build_status_counts(posts):
    counts = Counter(post["status"] for post in posts)
    return {
        "Draft": counts.get("Draft", 0),
        "Scheduled": counts.get("Scheduled", 0),
        "Published": counts.get("Published", 0),
        "Failed": counts.get("Failed", 0),
    }


def build_platform_counts(posts):
    return Counter(post["platform"] for post in posts)
