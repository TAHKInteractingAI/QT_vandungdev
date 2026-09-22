"""Backlot server — FastAPI app: board state API, SSE change feed, media.

The watcher observes ``projects/`` with watchfiles; on any change it bumps a
per-project version and wakes SSE subscribers, who tell the browser to
refetch state. The server never writes to project directories.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from openmontage.backlot.model_catalog import default_model, is_selectable, models_for
from openmontage.backlot.state import PROJECTS_DIR, REPO_ROOT, summarize_project
from openmontage.lib.env_loader import load_env

load_env()

UI_DIR = Path(__file__).resolve().parent / "ui"
THUMB_CACHE_DIR = REPO_ROOT / ".backlot" / "thumbs"
THUMB_WIDTHS = (320, 640, 960)

# Paths inside a project whose changes are pure noise for the board.
_IGNORE_PARTS = {"node_modules", ".git", "__pycache__", ".cache"}

SSE_HEARTBEAT_SECONDS = 15
_GENERATION_FIELDS = {
    "operation", "provider", "prompt", "narration", "language", "preset", "image_data",
    "model",
}
_SECRET_FIELD_NAMES = {"api_key", "api_secret", "access_key", "token", "secret", "authorization", "credentials"}


def _credential_configured(item: dict) -> bool:
    for env_name in item.get("credential_env", ()):
        value = os.environ.get(env_name)
        if not value:
            continue
        if env_name.endswith("CREDENTIALS"):
            return Path(value).is_file()
        return True
    return False


def _model_availability(item: dict) -> dict:
    """Add safe provider status without exposing credential values."""
    result = dict(item)
    configured = _credential_configured(item)
    result["configured"] = configured
    result["available"] = bool(item.get("selectable") and configured)
    if not configured:
        result["availability_reason"] = "Google credential is not configured."
    elif not item.get("selectable"):
        result["availability_reason"] = item.get("note") or "Model is not selectable in Backlot."
    else:
        result["availability_reason"] = "Credential configured; provider access is checked during generation."
    return result


def _ui_html(
    name: str,
    assets: tuple[str, ...],
    *,
    title: str | None = None,
    page_class: str = "",
    active_page: str = "",
    use_base: bool = True,
) -> HTMLResponse:
    page = (UI_DIR / name).read_text(encoding="utf-8")
    if not use_base:
        html = page
        for asset in assets:
            path = UI_DIR / asset
            if path.is_file():
                version = str(int(path.stat().st_mtime))
                html = html.replace(f"/ui/{asset}", f"/ui/{asset}?v={version}")
        return HTMLResponse(html)

    base = (UI_DIR / "base.html").read_text(encoding="utf-8")
    links = ['<link rel="stylesheet" href="/ui/base.css">']
    scripts: list[str] = []
    for asset in assets:
        path = UI_DIR / asset
        if not path.is_file():
            continue
        version = str(int(path.stat().st_mtime))
        url = f"/ui/{asset}?v={version}"
        if asset.endswith(".css"):
            links.append(f'<link rel="stylesheet" href="{url}">')
        elif asset.endswith(".js"):
            scripts.append(f'<script type="module" src="{url}"></script>')

    active = {f"{name}_active": "active" if active_page == name else "" for name in ("create", "library")}
    html = base.replace("{{PAGE_TITLE}}", title or "OpenMontage")
    html = html.replace("{{PAGE_CLASS}}", page_class)
    html = html.replace("{{PAGE_ASSETS}}", "\n".join(links))
    html = html.replace("{{PAGE_SCRIPTS}}", "\n".join(scripts))
    html = html.replace("{{PAGE_CONTENT}}", page)
    for token, value in active.items():
        html = html.replace("{{" + token.upper() + "}}", value)
    return HTMLResponse(html)


class ChangeHub:
    """Fan-out of project-change notifications to SSE subscribers.

    Subscriptions are filtered: a board subscribed to one project only ever
    receives that project's ids, so unrelated-project bursts can't flood its
    queue and starve out the one notification it actually needs.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, project_id: Optional[str] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers[q] = project_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def publish(self, project_id: str) -> None:
        for q, only in list(self._subscribers.items()):
            if only is not None and only != project_id:
                continue
            try:
                q.put_nowait(project_id)
            except asyncio.QueueFull:
                # Queue holds only THIS subscriber's relevant ids, so a full
                # queue already guarantees a pending wake-up → safe to drop.
                pass


hub = ChangeHub()

# Library summaries are expensive to derive (full state parse per project);
# cache per project and invalidate from the watcher.
_summary_cache: dict[str, dict] = {}


def _invalidate_summary(project_id: str) -> None:
    _summary_cache.pop(project_id, None)


def _cached_summaries() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    summaries = []
    for entry in sorted(PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        cached = _summary_cache.get(entry.name)
        if cached is None:
            try:
                cached = summarize_project(entry)
            except Exception:
                cached = {
                    "project_id": entry.name, "title": entry.name,
                    "pipeline_type": "unknown", "has_pipeline_state": False,
                    "poster": None, "live": False, "last_activity": 0,
                    "active_stage": None, "awaiting_human": False,
                    "stage_states": [], "completed_count": 0,
                    "render_count": 0, "scene_count": 0, "outputs": [], "error": "unreadable",
                }
            _summary_cache[entry.name] = cached
        summaries.append(cached)
    summaries.sort(key=lambda s: (not s["live"], -(s["last_activity"] or 0)))
    return summaries


# Watch-loop hot path: pure string comparison, no per-path filesystem calls
# (change batches can be thousands of paths during a render).
import os as _os

_PROJECTS_ROOT_STR = _os.path.normcase(str(PROJECTS_DIR.resolve()))


def _project_of_change(path_str: str) -> Optional[str]:
    """Map a changed filesystem path to a project id (None = irrelevant)."""
    norm = _os.path.normcase(_os.path.normpath(path_str))
    if not norm.startswith(_PROJECTS_ROOT_STR):
        return None
    rel = norm[len(_PROJECTS_ROOT_STR):].lstrip("\\/")
    if not rel:
        return None
    parts = rel.replace("\\", "/").split("/")
    if _IGNORE_PARTS.intersection(parts):
        return None
    return parts[0]


async def _watch_projects() -> None:
    """Background task: watch projects/ and publish debounced changes."""
    try:
        from watchfiles import awatch
    except ImportError:
        return  # watcher unavailable → board still works via manual refresh
    if not PROJECTS_DIR.is_dir():
        return
    async for changes in awatch(PROJECTS_DIR, recursive=True, step=400):
        touched: set[str] = set()
        for _change, path_str in changes:
            pid = _project_of_change(path_str)
            if pid:
                touched.add(pid)
        for pid in touched:
            _invalidate_summary(pid)
            hub.publish(pid)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Own and cleanly stop the project watcher with FastAPI's lifespan API."""

    task = asyncio.create_task(_watch_projects())
    app.state.watch_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="Backlot", docs_url=None, redoc_url=None, lifespan=_lifespan)

    # ---- API ----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "app": "backlot"}

    @app.post("/api/generate")
    async def generate(request: Request) -> dict:
        """Run one of the three media tools."""
        try:
            raw_payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")
        try:
            payload = _sanitize_generation_payload(raw_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return await asyncio.to_thread(_run_generation, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            return {"ok": False, "error": "generation failed"}

    @app.get("/api/models")
    async def models(operation: str | None = None) -> dict:
        allowed = {"text_to_image", "text_to_video", "image_to_video"}
        if operation is not None and operation not in allowed:
            raise HTTPException(status_code=400, detail="unsupported generation operation")
        return {
            "operation": operation,
            "models": [_model_availability(item) for item in models_for(operation, selectable_only=True)],
            "catalog": [_model_availability(item) for item in models_for(operation, selectable_only=False)],
            "defaults": {name: default_model(name) for name in sorted(allowed)},
        }

    @app.get("/api/projects")
    async def projects() -> list:
        return await asyncio.to_thread(_cached_summaries)

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str) -> dict:
        project_dir = _safe_project_dir(project_id)
        await asyncio.to_thread(shutil.rmtree, project_dir)
        _invalidate_summary(project_id)
        hub.publish(project_id)
        return {"ok": True, "project_id": project_id}

    @app.get("/api/library/events")
    async def library_events(request: Request) -> StreamingResponse:
        async def stream():
            q = hub.subscribe()
            try:
                yield _sse({"type": "hello"})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        changed = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": changed})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    # ---- Thumbnails (downscaled, cached on disk) ------------------------

    @app.get("/thumb/{project_id}/{file_path:path}")
    async def thumb(project_id: str, file_path: str, w: int = 640) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        width = min(THUMB_WIDTHS, key=lambda x: abs(x - w))
        cached = await asyncio.to_thread(_thumbnail_for, target, width)
        if cached is None:
            # Never fall back to raw video bytes for an <img> consumer (F-03);
            # non-thumbable images are safe to serve as-is.
            if target.suffix.lower() in {".mp4", ".webm", ".mov"}:
                raise HTTPException(status_code=404, detail="no poster frame available")
            return FileResponse(target)
        return FileResponse(cached, media_type="image/jpeg")

    # ---- Media (range requests handled by FileResponse) ---------------

    @app.get("/media/{project_id}/{file_path:path}")
    async def media(project_id: str, file_path: str) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(target)

    # ---- UI ------------------------------------------------------------

    @app.get("/")
    async def creator_page() -> HTMLResponse:
        return _ui_html("create.html", ("create.css", "create.js"), title="OpenMontage — Create", page_class="creator-page", active_page="create")

    @app.get("/library")
    async def library_page() -> HTMLResponse:
        return _ui_html("index.html", ("library.css", "library.js"), title="OpenMontage — Library", page_class="library-page", active_page="library")

    if UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    # Browsers heuristically cache /ui assets. no-cache forces a conditional
    # revalidation (cheap 304 via ETag) on every load so UI fixes show up on a
    # plain refresh. Media/thumb responses keep normal caching.
    @app.middleware("http")
    async def ui_no_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path == "/library" or path.startswith("/ui"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def _save_uploaded_image(payload: dict, root: Path) -> Path | None:
    image_data = payload.get("image_data")
    if not image_data:
        return None
    if not isinstance(image_data, str) or "," not in image_data:
        raise ValueError("image_data must be a data URL")
    header, encoded = image_data.split(",", 1)
    if not header.startswith("data:image/"):
        raise ValueError("only image uploads are supported")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError(f"invalid image upload: {exc}")
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("image upload is limited to 15 MB")
    mime = header.split(";", 1)[0][5:]
    suffix = mimetypes.guess_extension(mime) or ".png"
    path = root / "inputs" / f"reference{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _sanitize_generation_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    suspicious = {
        str(key).lower()
        for key in payload
        if any(secret in str(key).lower() for secret in _SECRET_FIELD_NAMES)
    }
    if suspicious:
        raise ValueError("API credentials must be configured in the environment, not sent with a generation request")
    return {key: value for key, value in payload.items() if key in _GENERATION_FIELDS}


def _run_generation(payload: dict) -> dict:
    operation = str(payload.get("operation") or "").strip()
    if operation not in {"text_to_image", "text_to_video", "image_to_video"}:
        raise ValueError("operation must be text_to_image, text_to_video, or image_to_video")
    model = str(payload.get("model") or default_model(operation)).strip()
    if not is_selectable(operation, model):
        raise ValueError(f"model is not supported for {operation}: {model}")

    from openmontage.tools.graphics.google_imagen import GoogleImagen
    from openmontage.tools.news_video import NewsVideo
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    preset = str(payload.get("preset") or "tiktok")
    if preset not in {"tiktok", "youtube"}:
        raise ValueError("preset must be tiktok or youtube")
    language = str(payload.get("language") or "vi")
    if language not in {"vi", "en"}:
        raise ValueError("language must be vi or en")

    project_id = f"ui-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    root = PROJECTS_DIR / project_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "request.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    image_path = _save_uploaded_image(payload, root)

    if operation == "text_to_image":
        output = root / "image.png"
        result = GoogleImagen().execute({
            "prompt": prompt,
            "aspect_ratio": "9:16" if preset == "tiktok" else "16:9",
            "model": model,
            "output_path": str(output),
        })
        if not result.success:
            return {"ok": False, "error": result.error, "project_id": project_id, "model": model}
        return {"ok": True, "project_id": project_id, "operation": operation, "model": model, "files": ["image.png"], "message": "Image generated via API and saved locally."}

    if model == "gemini-omni-1.1-flash":
        from openmontage.tools.video.gemini_omni_video import GeminiOmniVideo

        omni_inputs = {
            "operation": operation,
            "prompt": prompt,
            "aspect_ratio": "9:16" if preset == "tiktok" else "16:9",
            "output_path": str(root / "video.mp4"),
        }
        if operation == "image_to_video":
            if not image_path:
                return {"ok": False, "error": "image_to_video requires a reference image.", "project_id": project_id}
            omni_inputs["reference_image_path"] = str(image_path)
        result = GeminiOmniVideo().execute(omni_inputs)
        if not result.success:
            return {"ok": False, "error": result.error, "project_id": project_id, "model": model}
        return {"ok": True, "project_id": project_id, "operation": operation, "model": model, "files": ["video.mp4"], "message": "Video generated via Gemini Omni API and saved locally."}

    result = NewsVideo().execute({
        "operation": "render",
        "title": project_id,
        "source_text": prompt,
        "script": str(payload.get("narration") or prompt).strip(),
        "sources": ["ui://local-prompt"],
        "language": language,
        "preset": preset,
        "output_dir": str(PROJECTS_DIR),
        "visual_mode": operation,
        "reference_image_path": str(image_path) if image_path else None,
        "video_model": model,
        "motion_scene_count": 3,
        "text_to_video_scene_count": 1,
    })
    if not result.success:
        return {"ok": False, "error": result.error, "project_id": project_id, "model": model}
    output_path = Path(result.data["output_path"])
    project_dir = output_path.parent
    project_id = project_dir.name
    files = []
    for artifact in result.artifacts:
        path = Path(artifact)
        try:
            files.append(path.resolve().relative_to(project_dir.resolve()).as_posix())
        except ValueError:
            pass
    return {"ok": True, "project_id": project_id, "operation": operation, "model": model, "files": files, "message": "Video generated via API and composed locally."}


def _safe_project_dir(project_id: str) -> Path:
    # ':' rejects Windows drive-relative ids like "C:" (PROJECTS_DIR / "C:"
    # collapses back to PROJECTS_DIR itself).
    if any(c in project_id for c in "/\\:") or project_id in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid project id")
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"unknown project: {project_id}")
    return project_dir


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _thumbnail_for(source: Path, width: int) -> Optional[Path]:
    """Downscale an image (or extract a video poster frame) to a cached JPEG."""
    suffix = source.suffix.lower()
    is_image = suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    is_video = suffix in {".mp4", ".webm", ".mov"}
    if not (is_image or is_video):
        return None
    try:
        import hashlib
        stat = source.stat()
        key = hashlib.sha1(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
        ).hexdigest()[:20]
        cached = THUMB_CACHE_DIR / f"{key}.jpg"
        if cached.is_file():
            return cached
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Unique temp per request — concurrent misses for the same source
        # must not write (and replace from) the same temp file.
        import uuid
        tmp = THUMB_CACHE_DIR / f"{key}.{uuid.uuid4().hex[:8]}.tmp.jpg"
        if is_video:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5",
                 "-i", str(source), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", str(tmp)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not tmp.is_file():
                return None
        else:
            from PIL import Image
            with Image.open(source) as img:
                img = img.convert("RGB")
                img.thumbnail((width, width * 3))
                img.save(tmp, "JPEG", quality=82)
        tmp.replace(cached)
        return cached
    except Exception:
        return None


app = create_app()
