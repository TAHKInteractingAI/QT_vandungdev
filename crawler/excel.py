from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook
from openpyxl.packaging.manifest import mimetypes as openpyxl_mimetypes
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

openpyxl_mimetypes.add_type("image/webp", ".webp")

_HEADERS = ["#", "Title", "Source", "Google News URL", "Publisher URL", "Published", "Snippet", "Preview", "Image", "Status"]
_WIDTHS = [5, 42, 14, 30, 30, 18, 42, 16, 28, 26]


def _style_header(ws):
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_HEADERS))}1"
    for idx, w in enumerate(_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    if ws.sheet_properties.pageSetUpPr:
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def _add_hyperlinks(ws, row_idx: int, art: dict, img_rel: str = ""):
    try:
        if link := art.get("publisher_url") or art.get("google_url", ""):
            ws.cell(row=row_idx, column=5).hyperlink = link
            ws.cell(row=row_idx, column=5).style = "Hyperlink"
        if g_link := art.get("google_url", ""):
            ws.cell(row=row_idx, column=4).hyperlink = g_link
            ws.cell(row=row_idx, column=4).style = "Hyperlink"
        if img_rel:
            ws.cell(row=row_idx, column=9).hyperlink = img_rel
            ws.cell(row=row_idx, column=9).style = "Hyperlink"
    except Exception:
        pass


def _embed_preview(ws, row_idx: int, thumb_path: Path, max_w: int = 100, max_h: int = 75):
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
            ws.add_image(xl, f"H{row_idx}")
        ws.row_dimensions[row_idx].height = 60
    except Exception:
        pass


def export_excel(articles: list[dict], output_dir: Path, images_dir_name: str = "images") -> Path:
    xlsx_path = output_dir / "articles.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Articles"
    ws.append(_HEADERS)
    _style_header(ws)

    # Sort articles by original order if present
    sorted_articles = sorted(articles, key=lambda a: a.get("order", 0)) if any("order" in a for a in articles) else list(articles)

    for i, art in enumerate(sorted_articles, 1):
        order_num = art.get("order", i)
        imgs: list[Path] = art.get("saved_images", [])  # type: ignore
        img_paths = [Path(p) for p in imgs] if imgs else []
        img_rel = f"{images_dir_name}/{img_paths[0].name}" if len(img_paths) >= 1 else ""

        # Friendly anchor text for URLs to prevent long unbroken strings expanding row height in Excel
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
            art.get("title", ""),
            art.get("source", ""),
            g_label,
            pub_label,
            art.get("published", ""),
            art.get("snippet", ""),
            "",  # Column 8: Preview thumbnail
            img_rel,
            art.get("status", "ok"),
        ])
        row_idx = i + 1
        _add_hyperlinks(ws, row_idx, art, img_rel=img_rel)
        if img_paths:
            _embed_preview(ws, row_idx, img_paths[0])
        ws.row_dimensions[row_idx].height = 60

    # User requirement: wrap text + Align Top + Align Left for text, Center for # and Preview
    align_text = Alignment(wrap_text=True, vertical="top", horizontal="left")
    align_center = Alignment(vertical="top", horizontal="center")

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(_HEADERS)):
        for col_idx, cell in enumerate(row, 1):
            if col_idx in (1, 8):  # '#' and 'Preview'
                cell.alignment = align_center
            else:
                cell.alignment = align_text

    wb.save(xlsx_path)
    return xlsx_path


def export_excel_from_jsonl(jsonl_path: str | Path, output_dir: str | Path | None = None) -> Path:
    """Re-export Excel articles.xlsx from an existing articles.jsonl checkpoint."""
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
            # Reconstruct Path objects for saved_images
            if raw_imgs := art.get("saved_images"):
                art["saved_images"] = [Path(p) for p in raw_imgs]
            articles.append(art)

    # Sort articles by original order so Excel order is strictly consistent
    articles.sort(key=lambda a: a.get("order", 0))
    return export_excel(articles, out_dir)
