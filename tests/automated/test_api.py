from fastapi.testclient import TestClient
from crawler.api.app import app
from crawler.api.config import settings

client = TestClient(app)


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "google-news-crawler-api"
    assert "timestamp" in data


def test_trigger_unauthorized():
    # Request without X-API-Key header
    response = client.post("/api/v1/crawl/trigger", json={"keyword": "Trillion"})
    assert response.status_code == 401
    assert "Unauthorized" in response.json()["detail"]


def test_trigger_authorized_with_full_cli_params():
    headers = {"X-API-Key": settings.CRON_API_KEY}
    payload = {
        "keyword": "Trillion",
        "max_articles": 2,
        "workers": 2,
        "lang": "top",
        "timeout": 12,
        "proxy": None,
        "rotate_ua": True,
        "resume": True,
        "show_progress": False,
        "time_window": "1d",
    }

    # Trigger first job with full CLI parameters
    res1 = client.post("/api/v1/crawl/trigger", json=payload, headers=headers)
    assert res1.status_code == 202
    data1 = res1.json()
    assert "job_id" in data1
    assert data1["status"] in ("pending", "running")
    assert data1["keyword"] == payload["keyword"]
    assert data1["max_articles"] == 2
    assert data1["workers"] == 2
    assert data1["lang"] == "top"
    assert "markets" in data1
    assert len(data1["markets"]) >= 4
    assert data1["time_window"] == "1d"
    assert data1["timeout"] == 12
    assert data1["rotate_ua"] is True
    assert data1["resume"] is True
    assert data1.get("timezone") == "Asia/Ho_Chi_Minh"

    # Trigger second job immediately -> Concurrency Lock must return 409 Conflict
    res2 = client.post("/api/v1/crawl/trigger", json=payload, headers=headers)
    assert res2.status_code == 409
    assert "Concurrency lock is active" in res2.json()["detail"]


def test_trigger_custom_timezone_get():
    """Verify triggering job with custom timezone (e.g. UTC, Asia/Tokyo) via GET/query."""
    import time
    from crawler.api.services.job_manager import job_manager

    # Wait for previous background job to finish if needed
    for _ in range(120):
        if not job_manager.is_running():
            break
        time.sleep(0.5)
    assert not job_manager.is_running(), "Previous background job took too long to finish"

    headers = {"X-API-Key": settings.CRON_API_KEY}
    res = client.get("/api/v1/crawl/trigger?keyword=TimezoneTest&max=1&tz=UTC", headers=headers)
    assert res.status_code == 202
    data = res.json()
    assert data["keyword"] == "TimezoneTest"
    assert data["timezone"] == "UTC"
    assert "TimezoneTest_" in data["job_id"]


def test_download_excel_verification():
    """
    Test endpoint for downloading output Excel file and inspect binary file content.
    """
    import io
    import openpyxl
    from crawler.sheet_schema import HEADERS

    job = client.get("/api/v1/jobs/latest")
    assert job.status_code == 200
    job_data = job.json()

    if job_data.get("status") == "completed":
        job_id = job_data["job_id"]
        res = client.get(f"/api/v1/jobs/{job_id}/download/excel")
        assert res.status_code == 200
        assert "spreadsheetml" in res.headers["content-type"]
        assert len(res.content) > 1000

        from pathlib import Path
        output_dir = Path("tests/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "test_api_downloaded.xlsx").write_bytes(res.content)

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        assert len(wb.sheetnames) > 0
        ws = wb.active
        assert ws is not None
        headers = [c.value for c in ws[1]]
        assert headers == HEADERS
        assert ws.max_row > 1, "Excel file must contain at least 1 data row"
        wb.close()


def test_download_json_verification():
    """
    Test endpoint for downloading output JSON file and inspect JSON content.
    """
    job = client.get("/api/v1/jobs/latest")
    assert job.status_code == 200
    job_data = job.json()

    if job_data.get("status") == "completed":
        job_id = job_data["job_id"]
        res = client.get(f"/api/v1/jobs/{job_id}/download/json")
        assert res.status_code == 200
        assert "application/json" in res.headers["content-type"]
        items = res.json()
        assert isinstance(items, list)
        assert len(items) > 0
        assert "title" in items[0]


def test_trigger_with_ping_url():
    """Verify triggering job with ping_url via POST and GET query param."""
    import time
    from crawler.api.services.job_manager import job_manager

    # Wait for previous background job to finish if needed
    for _ in range(120):
        if not job_manager.is_running():
            break
        time.sleep(0.5)
    assert not job_manager.is_running(), "Previous background job took too long to finish"

    headers = {"X-API-Key": settings.CRON_API_KEY}
    test_ping = "https://cron-job.org/ping/test-uuid-12345"
    res = client.get(f"/api/v1/crawl/trigger?keyword=PingTest&max=1&ping_url={test_ping}", headers=headers)
    assert res.status_code == 202
    data = res.json()
    assert data["keyword"] == "PingTest"
    assert data["ping_url"] == test_ping

