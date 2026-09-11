from crawler.proxy_manager import ProxyManager, DEFAULT_BACKBONE_PROXY

def test_proxy_manager_singleton():
    pm1 = ProxyManager.get_instance()
    pm2 = ProxyManager.get_instance()
    assert pm1 is pm2

def test_proxy_manager_api_fetch():
    pm = ProxyManager.get_instance()
    # Ensure api_key is populated from .env
    assert pm.get_api_key() != ""
    
    proxies = pm.fetch_active_proxies()
    assert len(proxies) > 0
    for p in proxies:
        assert p.startswith("http://")
        assert "@" in p

def test_proxy_manager_failover_rotation():
    pm = ProxyManager.get_instance()
    # Attempt 0 without explicit proxy -> backbone rotating
    p0 = pm.get_proxy(None, attempt=0)
    assert p0 == DEFAULT_BACKBONE_PROXY

    # Attempt 1, 2 on retry -> rotates to different IPs from active pool
    p1 = pm.get_proxy(None, attempt=1)
    p2 = pm.get_proxy(None, attempt=2)
    assert p1 is not None
    assert p2 is not None
    assert p1 != p2
