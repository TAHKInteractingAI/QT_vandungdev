from __future__ import annotations

from typing import Any

# Standard 10 headers across Google Sheets & Excel
HEADERS = [
    "#",
    "Preview",
    "Title",
    "Snippet",
    "Published",
    "Source",
    "Google News URL",
    "Publisher URL",
    "Image",
    "Status",
]

# Column specifications mapping 1:1 between Google Sheet pixel widths and Excel openpyxl widths
COLUMN_SPECS: list[dict[str, Any]] = [
    {"header": "#",               "pixel_width": 45,  "excel_width": 6,  "align": "center"},
    {"header": "Preview",         "pixel_width": 145, "excel_width": 20, "align": "center"},
    {"header": "Title",           "pixel_width": 300, "excel_width": 40, "align": "left"},
    {"header": "Snippet",         "pixel_width": 300, "excel_width": 40, "align": "left"},
    {"header": "Published",       "pixel_width": 150, "excel_width": 20, "align": "left"},
    {"header": "Source",          "pixel_width": 100, "excel_width": 14, "align": "left"},
    {"header": "Google News URL", "pixel_width": 200, "excel_width": 27, "align": "left"},
    {"header": "Publisher URL",   "pixel_width": 200, "excel_width": 27, "align": "left"},
    {"header": "Image",           "pixel_width": 200, "excel_width": 27, "align": "left"},
    {"header": "Status",          "pixel_width": 200, "excel_width": 27, "align": "left"},
]

# Row heights (enlarged for preview images)
ROW_HEIGHT_PX = 86      # For Google Sheets
ROW_HEIGHT_EXCEL = 86   # For openpyxl points
PREVIEW_MAX_W = 145     # Max thumbnail width
PREVIEW_MAX_H = 105     # Max thumbnail height
