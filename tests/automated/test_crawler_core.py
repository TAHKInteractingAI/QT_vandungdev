"""
Unit test verifying Google News crawler core execution,
cross-verifying search results and inspecting actual output Excel evidence.
"""
import json
from pathlib import Path
import openpyxl
from crawler.core import crawl_google_news
from crawler.sheet_schema import HEADERS


def test_crawler_core_comprehensive_verification(tmp_path: Path):
    output_dir = tmp_path / "smoke_output"
    keyword = "Trillion"
    max_articles = 2
    res = crawl_google_news(
        keyword=keyword,
        max_articles=max_articles,
        output_dir=output_dir,
        workers=2,
        show_progress=False,
    )

    # 1. Cross-verify search results
    assert res["discovered"] > 0, "Should discover at least 1 article from Google News RSS"
    assert res["processed"] > 0, "Should process at least 1 article"
    assert res["decoded"] > 0, "Should decode publisher URL from Google CBM URL"

    # 2. Verify generated directories and files
    xlsx_path = Path(res["xlsx"])
    json_path = Path(res["json"])
    jsonl_path = Path(res["jsonl"])
    out_dir = Path(res["output_dir"])
    img_dir = Path(res["images_dir"])

    assert xlsx_path.exists(), "Output Excel file (articles.xlsx) must exist"
    assert json_path.exists(), "Complete articles.json file must exist"
    assert jsonl_path.exists(), "Checkpoint articles.jsonl file must exist"
    assert out_dir.exists(), "Output directory must exist"
    assert img_dir.exists(), "Images directory must exist"

    # Save physical copy in tests/output for immediate user inspection
    test_output_dir = Path("tests/output")
    test_output_dir.mkdir(parents=True, exist_ok=True)
    persisted_xlsx = test_output_dir / "test_crawler_core.xlsx"
    import shutil
    shutil.copy2(xlsx_path, persisted_xlsx)
    print(f"\n[EVIDENCE] Saved physical Excel file: {persisted_xlsx.resolve()}")

    # 3. Read articles.jsonl for 1-to-1 cross-verification with Excel
    articles_from_jsonl = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                articles_from_jsonl.append(json.loads(line))

    assert len(articles_from_jsonl) == res["processed"], "Article count in JSONL must match processed count"

    # Sort by order to match Excel layout
    articles_from_jsonl.sort(key=lambda a: a.get("order", 0))

    # 4. Deep verify Excel spreadsheet contents
    wb = openpyxl.load_workbook(xlsx_path, data_only=False)
    assert len(wb.sheetnames) > 0, "Excel file must contain at least one sheet"
    ws = wb.active
    assert ws is not None

    # 4.1. Verify column headers
    actual_headers = [cell.value for cell in ws[1]]
    assert actual_headers == HEADERS, f"Excel headers mismatch. Expected: {HEADERS}, Actual: {actual_headers}"

    # 4.2. Verify row count
    total_data_rows = ws.max_row - 1
    assert total_data_rows == len(articles_from_jsonl), (
        f"Data row count in Excel ({total_data_rows}) must match JSONL count ({len(articles_from_jsonl)})"
    )

    # 4.3. Row-by-row cell cross-verification
    # Column layout: 1: #, 2: Preview, 3: Title, 4: Snippet, 5: Published, 6: Source, 7: Google News URL, 8: Publisher URL, 9: Image, 10: Status
    for row_idx, art in enumerate(articles_from_jsonl, start=2):
        row_num = ws.cell(row=row_idx, column=1).value
        # column 2 is Preview thumbnail
        title = ws.cell(row=row_idx, column=3).value
        snippet = ws.cell(row=row_idx, column=4).value
        published = ws.cell(row=row_idx, column=5).value
        source = ws.cell(row=row_idx, column=6).value
        g_news_label = ws.cell(row=row_idx, column=7).value
        pub_label = ws.cell(row=row_idx, column=8).value
        img_rel = ws.cell(row=row_idx, column=9).value
        status = ws.cell(row=row_idx, column=10).value

        # Verify order number
        assert row_num == art.get("order", row_idx - 1), f"Row {row_idx}: Order mismatch"
        # Verify title
        assert title == art.get("title", ""), f"Row {row_idx}: Title mismatch"
        # Verify snippet
        assert snippet == art.get("snippet", ""), f"Row {row_idx}: Snippet mismatch"
        # Verify published date
        assert published == art.get("published", ""), f"Row {row_idx}: Published mismatch"
        # Verify source
        assert source == art.get("source", ""), f"Row {row_idx}: Source mismatch"

        # Verify publisher hyperlink
        if art.get("publisher_url"):
            pub_cell = ws.cell(row=row_idx, column=8)
            assert pub_cell.hyperlink is not None, f"Row {row_idx}: Publisher cell must have a clickable hyperlink"
            assert pub_cell.hyperlink.target == art.get("publisher_url"), f"Row {row_idx}: Hyperlink target mismatch"

        # Verify image file presence on disk if images were saved
        if art.get("saved_images"):
            assert img_rel != "", f"Row {row_idx}: Image column must have relative image path"
            for p in art["saved_images"]:
                img_file = Path(p)
                assert img_file.exists(), f"Image file {img_file} must exist on disk"
                assert img_file.stat().st_size > 0, f"Image file {img_file} must not be empty (0 bytes)"

            # Verify standard row height of 86pt for enlarged preview image rendering
            assert ws.row_dimensions[row_idx].height == 86, f"Row {row_idx}: Row height must be 86pt"

    wb.close()
