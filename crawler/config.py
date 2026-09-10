import random

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 10
DEFAULT_KEYWORD = "Trillion"
DEFAULT_LANG = "vi"  # Default market/locale key in SUPPORTED_LOCALES
DEFAULT_WORKERS = 5
POOL_CONNECTIONS = 20
POOL_MAXSIZE = 20
DEFAULT_PROXY: str | None = None
DEFAULT_TIME_WINDOW: str | None = None  # e.g. "1d" (24h), "2d" (48h), "7d", "1h"
PLACEHOLDER_HOSTS = ("googleusercontent.com", "gstatic.com", "google.com/images", "gnews/logo", "lh3.googleusercontent")

# Standardized multi-market Google News RSS configurations
SUPPORTED_LOCALES: dict[str, dict[str, str]] = {
    # 1. Vietnam & Southeast Asia
    "vi": {"lang": "vi", "country": "VN", "ceid": "VN:vi", "name": "Vietnam (Tiếng Việt)"},
    "vn": {"lang": "vi", "country": "VN", "ceid": "VN:vi", "name": "Vietnam (Tiếng Việt)"},
    "sg": {"lang": "en-SG", "country": "SG", "ceid": "SG:en", "name": "Singapore (English)"},
    "th": {"lang": "th", "country": "TH", "ceid": "TH:th", "name": "Thailand (ไทย)"},
    "id": {"lang": "id", "country": "ID", "ceid": "ID:id", "name": "Indonesia (Bahasa)"},

    # 2. North America
    "us": {"lang": "en-US", "country": "US", "ceid": "US:en", "name": "United States (English)"},
    "en": {"lang": "en-US", "country": "US", "ceid": "US:en", "name": "United States (English)"},
    "ca": {"lang": "en-CA", "country": "CA", "ceid": "CA:en", "name": "Canada (English)"},

    # 3. East Asia (Tech & Semiconductor Hubs)
    "jp": {"lang": "ja", "country": "JP", "ceid": "JP:ja", "name": "Japan (日本語)"},
    "ja": {"lang": "ja", "country": "JP", "ceid": "JP:ja", "name": "Japan (日本語)"},
    "kr": {"lang": "ko", "country": "KR", "ceid": "KR:ko", "name": "South Korea (한국어)"},
    "ko": {"lang": "ko", "country": "KR", "ceid": "KR:ko", "name": "South Korea (한국어)"},
    "cn": {"lang": "zh-CN", "country": "CN", "ceid": "CN:zh-Hans", "name": "China (简体中文)"},
    "zh": {"lang": "zh-CN", "country": "CN", "ceid": "CN:zh-Hans", "name": "China (简体中文)"},
    "tw": {"lang": "zh-TW", "country": "TW", "ceid": "TW:zh-Hant", "name": "Taiwan (繁體中文)"},

    # 4. Europe
    "uk": {"lang": "en-GB", "country": "GB", "ceid": "GB:en", "name": "United Kingdom (English)"},
    "gb": {"lang": "en-GB", "country": "GB", "ceid": "GB:en", "name": "United Kingdom (English)"},
    "de": {"lang": "de", "country": "DE", "ceid": "DE:de", "name": "Germany (Deutsch)"},
    "fr": {"lang": "fr", "country": "FR", "ceid": "FR:fr", "name": "France (Français)"},

    # 5. Emerging Markets & Oceania
    "in": {"lang": "en-IN", "country": "IN", "ceid": "IN:en", "name": "India (English)"},
    "au": {"lang": "en-AU", "country": "AU", "ceid": "AU:en", "name": "Australia (English)"},
}

# Pre-defined bundles for convenient multi-market crawls
LOCALE_PRESETS: dict[str, list[str]] = {
    "top": ["vi", "us", "uk", "sg"],
    "global": ["vi", "us", "uk", "sg", "jp", "de"],
    "asia": ["vi", "sg", "jp", "kr", "tw", "cn"],
    "tech": ["us", "tw", "kr", "jp", "cn"],
    "sea": ["vi", "sg", "th", "id"],
    "all": ["vi", "us", "uk", "sg", "jp", "kr", "cn", "tw", "de", "fr", "in", "au"],
}


def resolve_locales(
    lang_or_locales: str | list[str] | None = None,
    country: str | None = None,
) -> list[dict[str, str]]:
    """
    Resolve requested languages/locales into a deduplicated list of Google News locale configurations.
    Supports single codes (e.g. 'vi', 'us'), comma-separated strings ('vi,en,jp'),
    preset names ('top', 'global', 'tech'), or legacy custom (lang='vi', country='VN').
    """
    if not lang_or_locales and not country:
        return [SUPPORTED_LOCALES[DEFAULT_LANG]]

    # Case 1: Custom legacy lang + country combination not in presets
    if isinstance(lang_or_locales, str) and country and lang_or_locales.lower() not in SUPPORTED_LOCALES and lang_or_locales.lower() not in LOCALE_PRESETS:
        return [{
            "lang": lang_or_locales.strip(),
            "country": country.strip().upper(),
            "ceid": f"{country.strip().upper()}:{lang_or_locales.strip()}",
            "name": f"Custom ({country.strip().upper()}:{lang_or_locales.strip()})"
        }]

    # Case 2: Parse items from list or comma-separated string
    items: list[str] = []
    if isinstance(lang_or_locales, list):
        for it in lang_or_locales:
            items.extend([p.strip().lower() for p in str(it).split(",") if p.strip()])
    elif isinstance(lang_or_locales, str):
        items = [p.strip().lower() for p in lang_or_locales.split(",") if p.strip()]

    # Expand presets
    expanded_keys: list[str] = []
    for it in items:
        if it in LOCALE_PRESETS:
            expanded_keys.extend(LOCALE_PRESETS[it])
        elif it in SUPPORTED_LOCALES:
            expanded_keys.append(it)
        else:
            # Fallback: treat it as a direct language code with default US country or custom
            expanded_keys.append(it)

    if not expanded_keys:
        return [SUPPORTED_LOCALES.get(DEFAULT_LANG, {"lang": "vi", "country": "VN", "ceid": "VN:vi", "name": "Vietnam"})]

    # Deduplicate while preserving order based on ceid
    resolved: list[dict[str, str]] = []
    seen_ceids: set[str] = set()

    for k in expanded_keys:
        if k in SUPPORTED_LOCALES:
            cfg = SUPPORTED_LOCALES[k]
        else:
            c = country or "US"
            cfg = {"lang": k, "country": c, "ceid": f"{c}:{k}", "name": f"Custom ({c}:{k})"}

        if cfg["ceid"] not in seen_ceids:
            seen_ceids.add(cfg["ceid"])
            resolved.append(cfg)

    return resolved

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
]


def get_random_user_agent() -> str:
    """Return a random modern user agent string."""
    return random.choice(USER_AGENTS)
