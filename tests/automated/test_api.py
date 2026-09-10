from fastapi.testclient import TestClient
from api.app import app
from api.config import settings

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
        "lang": "vi",
        "country": "VN",
        "timeout": 12,
        "proxy": None,
        "rotate_ua": True,
        "resume": True,
        "show_progress": False,
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
    assert data1["lang"] == "vi"
    assert data1["country"] == "VN"
    assert data1["timeout"] == 12
    assert data1["rotate_ua"] is True
    assert data1["resume"] is True

    # Trigger second job immediately -> Concurrency Lock must return 409 Conflict
    res2 = client.post("/api/v1/crawl/trigger", json=payload, headers=headers)
    assert res2.status_code == 409
    assert "Concurrency lock is active" in res2.json()["detail"]


def test_download_excel_verification():
    """
    Test endpoint for downloading output Excel file and inspect binary file content.
    """
    import io
    import openpyxl
    from crawler.excel import _HEADERS

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
        assert "Articles" in wb.sheetnames
        ws = wb["Articles"]
        headers = [c.value for c in ws[1]]
        assert headers == _HEADERS
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
