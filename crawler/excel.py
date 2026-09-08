from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.packaging.manifest import mimetypes as openpyxl_mimetypes
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

openpyxl_mimetypes.add_type("image/webp", ".webp")

_HEADERS = ["#", "Title", "Source", "Google News URL", "Publisher URL", "Published", "Snippet", "Preview", "Images", "Status"]
_WIDTHS = [4, 42, 14, 32, 32, 18, 42, 16, 28, 30]


def _style_header(ws):
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_HEADERS))}1"
    for idx, w in enumerate(_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w
    if ws.sheet_properties.pageSetUpPr:
        ws.sheet_properties.pageSetUpPr.fitToPage = True


def _add_hyperlinks(ws, row_idx: int, art: dict, rel: str):
    try:
        if link := art.get("publisher_url") or art.get("google_url", ""):
            ws.cell(row=row_idx, column=5).hyperlink = link
            ws.cell(row=row_idx, column=5).style = "Hyperlink"
        if g_link := art.get("google_url", ""):
            ws.cell(row=row_idx, column=4).hyperlink = g_link
            ws.cell(row=row_idx, column=4).style = "Hyperlink"
        if rel:
            first = rel.split(";")[0].strip()
            if first:
                ws.cell(row=row_idx, column=9).hyperlink = first
                ws.cell(row=row_idx, column=9).style = "Hyperlink"
    except Exception:
        pass


def _embed_preview(ws, row_idx: int, thumb_path: Path):
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
            im.thumbnail((160, 120))
            bio = BytesIO()
            if im.mode in ("RGBA", "LA"):
                bg = PILImage.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                bg.save(bio, "PNG")
            else:
                im.convert("RGB").save(bio, "PNG")
            bio.seek(0)
            xl = XLImage(bio)
            xl.width = 100
            xl.height = 75
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

    for i, art in enumerate(articles, 1):
        imgs: list[Path] = art.get("saved_images", [])  # type: ignore
        rel = "; ".join(f"{images_dir_name}/{p.name}" for p in imgs) if imgs and isinstance(imgs[0], Path) else "; ".join(str(p) for p in imgs) if imgs else ""
        ws.append([i, art.get("title", ""), art.get("source", ""), art.get("google_url", ""), art.get("publisher_url", ""), art.get("published", ""), art.get("snippet", ""), "", rel, art.get("status", "ok")])
        row_idx = i + 1
        _add_hyperlinks(ws, row_idx, art, rel)
        if imgs:
            _embed_preview(ws, row_idx, Path(imgs[0]))
        else:
            ws.row_dimensions[row_idx].height = 15

    # snippet wrap once, not per-row loop
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=7, max_col=7):
        for c in row:
            c.alignment = c.alignment.copy(wrap_text=True, vertical="top")

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

    return export_excel(articles, out_dir)
