from __future__ import annotations

import os
import threading
import time
from typing import Any
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from crawler.config import TIMEOUT

# Webshare Backbone Rotating proxy endpoint (loaded purely from .env)
DEFAULT_BACKBONE_PROXY = os.getenv("DEFAULT_BACKBONE_PROXY")

class ProxyManager:
    """
    Manages proxy pool, dynamic retrieval via Webshare API, and failover rotation.
    Ensures zero 429 block on cloud datacenter IPs.
    """
    _instance: ProxyManager | None = None
    _lock = threading.Lock()

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("WEBSHARE_API_KEY", "")
        self._cached_proxies: list[dict[str, Any]] = []
        self._last_fetched: float = 0.0
        self._cache_ttl: float = 600.0  # 10 minutes cache
        self._current_index = 0

    @classmethod
    def get_instance(cls) -> ProxyManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_api_key(self) -> str:
        if not self.api_key:
            self.api_key = os.getenv("WEBSHARE_API_KEY", "")
        return self.api_key

    def fetch_active_proxies(self, force: bool = False) -> list[str]:
        """Fetch list of valid direct proxy URLs from Webshare API."""
        now = time.time()
        with self._lock:
            if not force and self._cached_proxies and (now - self._last_fetched < self._cache_ttl):
                return [p["url"] for p in self._cached_proxies if p.get("valid", True)]

            key = self.get_api_key()
            if not key:
                return []

            try:
                url = "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct"
                headers = {"Authorization": f"Token {key}"}
                resp = requests.get(url, headers=headers, timeout=TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    active_list: list[dict[str, Any]] = []
                    for item in results:
                        if item.get("valid", True):
                            u = item.get("username")
                            p = item.get("password")
                            ip = item.get("proxy_address")
                            port = item.get("port")
                            proxy_url = f"http://{u}:{p}@{ip}:{port}/"
                            active_list.append({
                                "id": item.get("id"),
                                "url": proxy_url,
                                "country": item.get("country_code"),
                                "valid": True,
                            })
                    if active_list:
                        self._cached_proxies = active_list
                        self._last_fetched = now
                        return [p["url"] for p in self._cached_proxies]
            except Exception as e:
                print(f"[ProxyManager] Notice: Failed to fetch Webshare proxy list: {e}")

            return [p["url"] for p in self._cached_proxies if p.get("valid", True)]

    def get_proxy(self, requested_proxy: str | None = None, attempt: int = 0) -> str | None:
        """
        Resolve best proxy:
        1. If user provided a specific proxy URL, return it on attempt 0. On retry (>0), fallback to rotating.
        2. If WEBSHARE_API_KEY is available:
           - On attempt 0: Return Backbone Rotating endpoint or first active proxy.
           - On attempt > 0: Rotate to another active IP from pool.
        3. Fallback to DEFAULT_BACKBONE_PROXY.
        """
        active = self.fetch_active_proxies()
        
        # If user explicitly gave a proxy and this is the first attempt
        if requested_proxy:
            if attempt == 0:
                return requested_proxy
            # If attempt > 0 and user proxy failed, fall back to rotating proxy or active pool
            if active:
                idx = (attempt - 1) % len(active)
                return active[idx]
            return DEFAULT_BACKBONE_PROXY

        # If we have fetched active proxies from Webshare API
        if active:
            if attempt == 0:
                # First attempt: Try backbone rotating if configured, else first active IP
                return DEFAULT_BACKBONE_PROXY or active[0]
            idx = (attempt - 1) % len(active)
            return active[idx]

        # Default fallback (may be None if neither API key nor backbone proxy configured)
        return DEFAULT_BACKBONE_PROXY


proxy_manager = ProxyManager.get_instance()
