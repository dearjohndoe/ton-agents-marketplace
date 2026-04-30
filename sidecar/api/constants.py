DESCRIBE_TIMEOUT = 10  # seconds
DYNAMIC_PRICE_CACHE_TTL = 60  # seconds
DEFAULT_QUOTE_TTL = 120  # seconds

MIME_EXT: dict[str, str] = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "audio/wav": ".wav", "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg", "video/mp4": ".mp4", "video/webm": ".webm",
    "application/pdf": ".pdf",
}

IMAGE_EXT_MIME: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
