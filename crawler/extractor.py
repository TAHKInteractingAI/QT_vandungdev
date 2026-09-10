from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

# Elements to remove entirely (do NOT include table, figure, or noscript blindly)
_JUNK_TAGS = {
    "script", "style", "nav", "header", "footer", "aside",
    "iframe", "svg", "button", "input", "form", "dialog", "menu",
}

# Substrings in class/id indicating non-article widgets or recommendations
_JUNK_KEYWORDS = {
    "menu", "footer", "header", "comment", "related", "recommend",
    "advert", "social", "share", "cookie", "modal", "popup", "login",
    "subscribe", "newsletter", "breadcrumb", "promo", "widget", "trending",
    "popular", "most-read", "tag-cloud", "ant-tabs", "ant-card", "marquee",
    "suggest", "more-news", "other-news", "box-category", "news-lead",
    "sidebar", "latest", "prev", "next", "navigation", "post-nav",
    "pagination", "read-more", "more-from", "related-posts", "category-news",
}

# High-priority content selectors
_BODY_SELECTORS = [
    ".article--layout-body",
    ".post-detail-body",
    ".article-body",
    ".article-content",
    ".detail-content",
    ".post-content",
    ".entry-content",
    ".text-content",
    ".content-detail",
    ".fck",
    "[itemprop='articleBody']",
    ".prose",
    ".wysiwyg",
    ".article__body",
    ".story-body",
    "main",
    "article",
    ".content",
]

_BULLET_PREFIX_REGEX = re.compile(r"^[\s\xa0·•●▪\-\*–—]+\s*")


def table_to_markdown(table_tag: Tag) -> str:
    """Convert an HTML <table> tag into a clean Markdown table format."""
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    matrix: list[list[str]] = []
    for r in rows:
        cells: list[str] = []
        for c in r.find_all(["th", "td"]):
            txt = c.get_text(separator=" ", strip=True)
            txt = txt.replace("\xa0", " ").strip()
            txt = re.sub(r"\s+", " ", txt)
            txt = txt.replace("|", "\\|")
            cells.append(txt)
        if any(cells):
            matrix.append(cells)

    if not matrix:
        return ""

    max_cols = max(len(r) for r in matrix)
    if max_cols == 0:
        return ""

    # Normalize row lengths
    for r in matrix:
        while len(r) < max_cols:
            r.append("")

    header = matrix[0]
    separator = ["---"] * max_cols

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for r in matrix[1:]:
        lines.append("| " + " | ".join(r) + " |")

    return "\n".join(lines)


def extract_content_and_images(html: str, base_url: str) -> tuple[str, list[dict]]:
    """
    Extract clean body text along with in-article images and HTML tables in sequential order.
    Returns:
        (markdown_text_with_image_placeholders, in_article_images_list)
    """
    if not html:
        return "", []

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return "", []

    # 1. First locate the best container BEFORE decomposing anything
    best_candidate: Tag | None = None
    best_text_len = 0

    for selector in _BODY_SELECTORS:
        candidates = soup.select(selector)
        for cand in candidates:
            txt_len = len(cand.get_text(strip=True))
            if txt_len > best_text_len and txt_len >= 200:
                best_text_len = txt_len
                best_candidate = cand
        if best_candidate and best_text_len >= 1000:
            break

    root = best_candidate or soup.body or soup

    # 2. Extract fallback images from <noscript> before decomposing <noscript> tags
    for ns in root.find_all("noscript"):
        for img in ns.find_all("img"):
            # Move valid img outside of noscript so it can be parsed
            ns.insert_before(img)
        ns.decompose()

    # 3. Decompose junk inside the selected root (protect tables, figures, charts)
    for tag in root.find_all(list(_JUNK_TAGS)):
        tag.decompose()

    for el in root.find_all(True):
        if not isinstance(el, Tag) or el.attrs is None or el is root:
            continue
        if el.name in ("table", "figure", "picture"):
            continue
        raw_classes = el.attrs.get("class", [])
        classes = " ".join(raw_classes if isinstance(raw_classes, list) else [str(raw_classes)]).lower()
        el_id = str(el.attrs.get("id", "")).lower()
        if "flourish" in classes or "datawrapper" in classes or "highcharts" in classes:
            continue
        if any(kw in classes or kw in el_id for kw in _JUNK_KEYWORDS):
            el.decompose()

    # 4. Extract text paragraphs, headings, bullet items, tables, and images in document order
    lines: list[str] = []
    seen_texts: set[str] = set()
    in_article_images: list[dict] = []
    seen_img_urls: set[str] = set()
    processed_tables: set[int] = set()

    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "img", "table", "figure"]):
        if not isinstance(el, Tag):
            continue

        # Handle HTML Table
        if el.name == "table":
            table_id = id(el)
            if table_id in processed_tables:
                continue
            processed_tables.add(table_id)
            md_table = table_to_markdown(el)
            if md_table:
                lines.append(md_table)
            continue

        # Prevent processing elements inside an already converted table
        if el.find_parent("table"):
            continue

        # Handle in-article images (including flourish/datawrapper chart thumbnails)
        if el.name == "img":
            # Skip navigation / card images wrapped in links pointing to another article
            parent_a = el.find_parent("a")
            if parent_a and parent_a.get("href"):
                continue

            src = el.get("src") or el.get("data-src") or el.get("data-original") or ""
            if not src or src.startswith("data:"):
                continue
            full_img_url = urljoin(base_url, src)
            low_url = full_img_url.lower()
            if any(bad in low_url for bad in ["logo", "icon", "avatar", "banner", "advert", "pixel", "button"]):
                continue
            if full_img_url in seen_img_urls:
                continue
            seen_img_urls.add(full_img_url)

            alt = (el.get("alt") or "").strip()
            placeholder = f"<!-- INLINE_IMAGE_{len(in_article_images) + 1:02d} -->"
            in_article_images.append({
                "placeholder": placeholder,
                "url": full_img_url,
                "alt": alt,
            })
            lines.append(placeholder)
            continue

        if el.name == "figure":
            figcaption = el.find("figcaption")
            if figcaption:
                cap_txt = figcaption.get_text(separator=" ", strip=True)
                if cap_txt and len(cap_txt) >= 10:
                    lines.append(f"*{cap_txt}*")
            continue

        # Filter out headings that are navigation links to other articles
        tag_name = el.name.lower()
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            a_tag = el.find("a") or el.find_parent("a")
            if a_tag:
                a_txt = a_tag.get_text(strip=True)
                tot_txt = el.get_text(strip=True)
                if len(a_txt) / max(1, len(tot_txt)) > 0.5:
                    continue

        # Prevent nested tags emitting duplicate text
        if el.find(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
            continue

        txt = el.get_text(separator=" ", strip=True)
        txt = txt.replace("\xa0", " ").strip()
        txt = re.sub(r"\s+", " ", txt).strip()

        if not txt or len(txt) < 15:
            continue

        if txt.lower() in seen_texts:
            continue
        seen_texts.add(txt.lower())

        is_bullet = False

        if tag_name == "li" or _BULLET_PREFIX_REGEX.match(txt):
            is_bullet = True
            cleaned_text = _BULLET_PREFIX_REGEX.sub("", txt)
        else:
            cleaned_text = txt

        if is_bullet:
            lines.append(f"- {cleaned_text}")
        elif tag_name == "h1":
            lines.append(f"# {txt}")
        elif tag_name == "h2":
            lines.append(f"## {txt}")
        elif tag_name == "h3":
            lines.append(f"### {txt}")
        elif tag_name in ("h4", "h5", "h6"):
            lines.append(f"#### {txt}")
        else:
            lines.append(txt)

    markdown_body = "\n\n".join(lines).strip()
    return markdown_body, in_article_images


def clean_html_to_markdown(html: str, base_url: str = "") -> str:
    """Legacy helper returning markdown text."""
    body, _ = extract_content_and_images(html, base_url)
    return body


def save_article_markdown(
    dest_path: Path,
    art: dict,
    content_markdown: str,
    img_rel: str = "",
    saved_images_map: dict[str, str] | None = None,
) -> Path:
    """
    Save article full content formatted in Markdown with metadata header.
    Replaces image placeholders with actual downloaded local paths.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    title = art.get("title", "No Title")
    source = art.get("source", "Unknown Source")
    published = art.get("published", "")
    pub_url = art.get("publisher_url") or art.get("google_url", "")

    header_lines = [
        f"# {title}",
        "",
        f"- **Source**: {source}",
        f"- **Published**: {published}",
        f"- **Original URL**: [{pub_url}]({pub_url})" if pub_url else "",
    ]
    if img_rel:
        header_lines.append(f"- **Lead Image**: ![{title}](../{img_rel})")

    header_lines = [line for line in header_lines if line]
    header_block = "\n".join(header_lines)

    body = content_markdown.strip() if content_markdown.strip() else "_No full text content could be extracted._"

    # Replace inline image placeholders with downloaded local relative paths
    if saved_images_map:
        for placeholder, local_img_path in saved_images_map.items():
            if local_img_path:
                body = body.replace(placeholder, f"![Image](../{local_img_path})")
            else:
                body = body.replace(placeholder, "")
    else:
        # If no local images map provided, clean up placeholders
        body = re.sub(r"<!-- INLINE_IMAGE_\d+ -->\n*", "", body)

    # Clean up multiple consecutive newlines
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    full_md = f"{header_block}\n\n---\n\n{body}\n"
    dest_path.write_text(full_md, encoding="utf-8")
    return dest_path
