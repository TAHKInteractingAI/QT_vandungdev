from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import openpyxl
from openpyxl import Workbook
from openpyxl.packaging.manifest import mimetypes as openpyxl_mimetypes
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from crawler.sheet_schema import (
    COLUMN_SPECS,
    HEADERS,
    PREVIEW_MAX_H,
    PREVIEW_MAX_W,
    ROW_HEIGHT_EXCEL,
)

openpyxl_mimetypes.add_type("image/webp", ".webp")


def _style_header(ws):
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}1"
    for idx, spec in enumerate(COLUMN_SPECS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = spec["excel_width"]
    if ws.sheet_properties.pageSetUpPr:
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def _add_hyperlinks(ws, row_idx: int, art: dict, img_rel: str = ""):
    try:
        # Col 7: Google News URL, Col 8: Publisher URL, Col 9: Image
        if g_link := art.get("google_url", ""):
            ws.cell(row=row_idx, column=7).hyperlink = g_link
            ws.cell(row=row_idx, column=7).style = "Hyperlink"
        if link := art.get("publisher_url") or art.get("google_url", ""):
            ws.cell(row=row_idx, column=8).hyperlink = link
            ws.cell(row=row_idx, column=8).style = "Hyperlink"
        if img_rel:
            ws.cell(row=row_idx, column=9).hyperlink = img_rel
            ws.cell(row=row_idx, column=9).style = "Hyperlink"
    except Exception:
        pass


def _embed_preview(ws, row_idx: int, thumb_path: Path, max_w: int = PREVIEW_MAX_W, max_h: int = PREVIEW_MAX_H):
    try:
        from io import BytesIO
        from openpyxl.drawing.image import Image as XLImage
        from PIL import Image as PILImage
    except Exception:
        return
    if not thumb_path.exists():
        return
    try:
        with PILImage.open(thumb_path) as im:
            im.thumbnail((max_w, max_h), PILImage.Resampling.LANCZOS)
            bio = BytesIO()
            if im.mode in ("RGBA", "LA"):
                bg = PILImage.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                bg.save(bio, "PNG")
            else:
                im.convert("RGB").save(bio, "PNG")
            bio.seek(0)
            xl = XLImage(bio)
            xl.width, xl.height = im.size
            # Column B is Preview
            ws.add_image(xl, f"B{row_idx}")
        ws.row_dimensions[row_idx].height = ROW_HEIGHT_EXCEL
    except Exception:
        pass


def populate_worksheet(ws, articles: list[dict], images_dir: Path | None = None) -> None:
    """Populate a single worksheet with standard header, rows, images and styling."""
    ws.append(HEADERS)
    _style_header(ws)

    sorted_articles = sorted(articles, key=lambda a: a.get("order", 0)) if any("order" in a for a in articles) else list(articles)

    for i, art in enumerate(sorted_articles, 1):
        order_num = art.get("order", i)
        imgs: list[Path] = art.get("saved_images", [])  # type: ignore
        img_paths = [Path(p) for p in imgs] if imgs else []
        img_rel = f"{img_paths[0].name}" if len(img_paths) >= 1 else ""

        g_url = art.get("google_url", "")
        g_label = "Google News" if g_url else ""

        pub_url = art.get("publisher_url", "")
        pub_label = ""
        if pub_url:
            try:
                domain = urlparse(pub_url).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                pub_label = domain or pub_url
            except Exception:
                pub_label = pub_url

        ws.append([
            order_num,
            "",  # Column 2 (B): Preview thumbnail
            art.get("title", ""),
            art.get("snippet", ""),
            art.get("published", ""),
            art.get("source", ""),
            g_label,
            pub_label,
            img_rel,
            art.get("status", "ok"),
        ])
        row_idx = i + 1
        _add_hyperlinks(ws, row_idx, art, img_rel=img_rel)
        if img_paths:
            _embed_preview(ws, row_idx, img_paths[0])
        ws.row_dimensions[row_idx].height = ROW_HEIGHT_EXCEL

    align_text = Alignment(wrap_text=True, vertical="top", horizontal="left")
    align_center = Alignment(vertical="top", horizontal="center")

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(HEADERS)):
        for col_idx, cell in enumerate(row, 1):
            if col_idx in (1, 2):  # '#' and 'Preview'
                cell.alignment = align_center
            else:
                cell.alignment = align_text


def export_excel(
    articles: list[dict],
    output_dir: Path,
    filename: str = "articles.xlsx",
    tab_name: str = "Articles",
    images_dir: Path | None = None,
) -> Path:
    """Create standalone workbook for current crawl run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = output_dir / filename
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = tab_name[:31]  # Excel tab title max 31 chars
    populate_worksheet(ws, articles, images_dir=images_dir)
    wb.save(xlsx_path)
    return xlsx_path


def append_to_master_excel(
    articles: list[dict],
    master_path: Path,
    tab_name: str,
    images_dir: Path | None = None,
) -> Path:
    """
    Append new crawl results as the FIRST worksheet (index=0) in master workbook.
    Matches Google Sheets behavior.
    """
    master_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized_tab = tab_name[:31]

    if master_path.exists():
        try:
            wb = openpyxl.load_workbook(master_path)
            # If tab already exists, append unique suffix
            if sanitized_tab in wb.sheetnames:
                sanitized_tab = f"{sanitized_tab[:26]}_{len(wb.sheetnames)}"
            ws = wb.create_sheet(title=sanitized_tab, index=0)
        except Exception:
            wb = Workbook()
            ws = wb.active
            assert ws is not None
            ws.title = sanitized_tab
    else:
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = sanitized_tab

    wb.active = 0  # Activate newest sheet at position 0
    populate_worksheet(ws, articles, images_dir=images_dir)
    wb.save(master_path)
    return master_path


def export_excel_from_jsonl(jsonl_path: str | Path, output_dir: str | Path | None = None) -> Path:
    """Re-export Excel from an existing articles.jsonl checkpoint."""
    jpath = Path(jsonl_path)
    if not jpath.exists():
        raise FileNotFoundError(f"JSONL checkpoint not found: {jpath}")

    out_dir = Path(output_dir) if output_dir else jpath.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    articles: list[dict] = []
    with open(jpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            art = json.loads(line)
            if raw_imgs := art.get("saved_images"):
                art["saved_images"] = [Path(p) for p in raw_imgs]
            articles.append(art)

    articles.sort(key=lambda a: a.get("order", 0))
    tab_name = jpath.parent.name or "Articles"
    return export_excel(articles, out_dir, filename=f"{tab_name}_articles.xlsx", tab_name=tab_name)
