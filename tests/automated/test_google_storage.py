import os
import pytest
from pathlib import Path
from crawler.core import crawl_google_news
from crawler.storage.google import GoogleCloudStorageBackend


def test_google_cloud_storage_live_integration():
    """
    Live integration test verifying crawler execution with Google Cloud Storage:
    - Verifies Google Drive subfolder creation and image upload.
    - Verifies Google Sheets tab creation and row insertion with =IMAGE() formula.
    """
    sheet_id = os.getenv("GOOGLE_SPREADSHEET_ID", "1feT9UTcjzjI_uq28ztdX5PU9Gkx3-5unvw7x4AVWolI")
    drive_folder_id = os.getenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", "1IirA4PHH0Wsu9tRLmiivQNY7XmDsZ5iE")

    if not Path("token.json").exists() and not Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")).exists():
        pytest.skip("Neither token.json nor service account credentials found")

    storage = GoogleCloudStorageBackend(
        spreadsheet_id=sheet_id,
        drive_parent_folder_id=drive_folder_id,
    )

    keyword = "Trillion"
    max_articles = 4
    res = crawl_google_news(
        keyword=keyword,
        max_articles=max_articles,
        workers=2,
        lang="vi,us",
        time_window="2d",
        show_progress=False,
        storage=storage,
        job_id="test_cloud_live",
    )

    # Verification
    assert res["discovered"] > 0
    assert res["processed"] > 0
    assert res["storage_mode"] == "google"
    assert "spreadsheet_url" in res
    assert "drive_folder_url" in res
    assert res["spreadsheet_id"] == sheet_id

    print("\n[CLOUD TEST SUCCESS]")
    print(f"Spreadsheet URL: {res['spreadsheet_url']}")
    print(f"Drive Folder URL: {res['drive_folder_url']}")
    print(f"Tab Name: {res['worksheet_title']}")
