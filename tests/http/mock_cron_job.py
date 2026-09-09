import io
from pathlib import Path
import time
import openpyxl
import requests

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "test-secret-key-123"


def simulate_cron_job():
    print("=" * 70)
    print("🚀 STARTING CRON-JOB.ORG MOCK SIMULATION WITH DEEP EXCEL EVIDENCE AUDIT")
    print("=" * 70)

    # 1. Healthcheck
    print("\n[cron-job.org MOCK] Step 1: Healthcheck & Uptime Inspection...")
    t0 = time.time()
    r_health = requests.get(f"{BASE_URL}/health")
    latency_health = time.time() - t0
    print(f"-> Status: {r_health.status_code} ({latency_health:.3f}s): {r_health.json()}")
    assert r_health.status_code == 200, "Healthcheck failed!"
    assert r_health.json()["status"] == "ok"

    # 2. Trigger Job
    keyword = "Artificial Intelligence"
    max_articles = 3
    workers = 2

    print(f"\n[cron-job.org MOCK] Step 2: Trigger Crawl Job (POST /trigger)...")
    print(f"   Parameters: keyword={keyword!r}, max_articles={max_articles}, workers={workers}")
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    payload = {"keyword": keyword, "max_articles": max_articles, "workers": workers}

    t0 = time.time()
    r_trigger = requests.post(f"{BASE_URL}/api/v1/crawl/trigger", json=payload, headers=headers)
    latency_trigger = time.time() - t0
    print(f"-> Response latency: {latency_trigger:.3f}s (Must be < 0.5s to prevent cron-job.org timeout)")
    print(f"-> Status: {r_trigger.status_code}, Body: {r_trigger.json()}")
    assert r_trigger.status_code == 202, f"Trigger failed: {r_trigger.text}"
    assert latency_trigger < 0.5, "Trigger response latency exceeded 0.5s threshold!"
    job_id = r_trigger.json()["job_id"]

    # 3. Poll progress
    print(f"\n[cron-job.org MOCK] Step 3: Polling Job Progress: {job_id}...")
    poll_count = 0
    while True:
        poll_count += 1
        r_status = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}")
        assert r_status.status_code == 200, f"Query job failed: {r_status.text}"
        data = r_status.json()
        status = data.get("status")
        print(f"   [Poll #{poll_count:02d}] Current status: {status} ...")
        if status in ("completed", "failed", "interrupted"):
            print(f"-> Finished with status: {status}")
            if status == "completed":
                print(f"-> Server execution stats: {data.get('stats')}")
            else:
                raise RuntimeError(f"Job failed unexpectedly: {status}, Error: {data.get('error')}")
            break
        time.sleep(2)

    stats = data["stats"]
    assert stats is not None, "Metadata stats must not be null"
    assert stats["keyword"] == keyword, "Result keyword must match request"
    assert stats["discovered"] > 0, "No articles discovered from Google News"
    assert stats["processed"] > 0, "No articles were processed"
    print(f"-> Cross-verification: Discovered {stats['discovered']} articles, successfully processed {stats['processed']}.")

    # 4. Download output Excel evidence
    print(f"\n[cron-job.org MOCK] Step 4: Downloading output Excel file...")
    r_excel = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}/download/excel")
    print(f"-> Excel download status: {r_excel.status_code}, Size: {len(r_excel.content)} bytes")
    assert r_excel.status_code == 200, "Failed to download Excel file!"
    assert len(r_excel.content) > 5000, "Excel file is suspiciously small (< 5KB)!"

    # Save physical file to disk for user inspection
    output_dir = Path("tests/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_excel_path = output_dir / f"mock_cron_{job_id}.xlsx"
    saved_excel_path.write_bytes(r_excel.content)
    latest_excel_path = output_dir / "latest_articles.xlsx"
    latest_excel_path.write_bytes(r_excel.content)
    print(f"-> Saved physical Excel file to disk: {saved_excel_path.resolve()}")
    print(f"-> Also updated latest Excel link: {latest_excel_path.resolve()}")

    # 5. Deep verify Excel spreadsheet contents
    print(f"\n[cron-job.org MOCK] Step 5: Deep inspecting spreadsheet contents with openpyxl...")
    excel_stream = io.BytesIO(r_excel.content)
    wb = openpyxl.load_workbook(excel_stream, data_only=False)
    assert "Articles" in wb.sheetnames, "Excel file missing 'Articles' sheet"
    ws = wb["Articles"]

    expected_headers = ["#", "Title", "Source", "Google News URL", "Publisher URL", "Published", "Snippet", "Preview", "Image", "Status"]
    actual_headers = [cell.value for cell in ws[1]]
    assert actual_headers == expected_headers, f"Header mismatch!\nExpected: {expected_headers}\nActual: {actual_headers}"
    print(f"   ✓ Column headers verified: {actual_headers}")

    data_rows = ws.max_row - 1
    assert data_rows == stats["processed"], f"Excel data rows ({data_rows}) mismatch processed count ({stats['processed']})!"
    print(f"   ✓ Excel data rows count: {data_rows} (matches 100% of processed articles)")

    # Row-by-row cell inspection
    for r in range(2, ws.max_row + 1):
        order_val = ws.cell(row=r, column=1).value
        title_val = ws.cell(row=r, column=2).value
        source_val = ws.cell(row=r, column=3).value
        gnews_cell = ws.cell(row=r, column=4)
        pub_cell = ws.cell(row=r, column=5)
        published_val = ws.cell(row=r, column=6).value
        snippet_val = ws.cell(row=r, column=7)
        img_rel_val = ws.cell(row=r, column=9).value
        status_val = ws.cell(row=r, column=10).value
        row_h = ws.row_dimensions[r].height

        assert order_val == r - 1, f"Row {r}: Order {order_val} is incorrect"
        assert title_val and len(str(title_val).strip()) > 0, f"Row {r}: Title must not be empty"
        assert source_val and len(str(source_val).strip()) > 0, f"Row {r}: Source must not be empty"
        assert published_val and len(str(published_val).strip()) > 0, f"Row {r}: Published must not be empty"
        assert row_h == 60, f"Row {r}: Row height must be 60pt (Actual: {row_h})"

        # Hyperlink inspection
        if pub_cell.value:
            assert pub_cell.hyperlink is not None, f"Row {r}: Publisher URL cell must have clickable hyperlink"
            assert str(pub_cell.hyperlink.target).startswith("http"), f"Row {r}: Hyperlink target must be a valid HTTP URL"

        print(f"   ✓ [Row {r}] #{order_val} | Source: {source_val} | Title: {str(title_val)[:40]}... | Status: {status_val}")

    wb.close()
    print("\n" + "=" * 70)
    print("🏆 ALL DATA CROSS-VERIFICATION & EXCEL EVIDENCE CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    simulate_cron_job()
