"""Shared helpers for API-backed video generation tools."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from openmontage.tools.base_tool import ToolResult


HEYGEN_PROVIDERS = {
    "veo_3_1": {"name": "Google VEO 3.1", "quality": "highest", "speed": "slow"},
    "veo_3_1_fast": {"name": "Google VEO 3.1 Fast", "quality": "high", "speed": "medium"},
    "veo3": {"name": "Google VEO 3", "quality": "high", "speed": "slow"},
    "veo3_fast": {"name": "Google VEO 3 Fast", "quality": "high", "speed": "medium"},
    "veo2": {"name": "Google VEO 2", "quality": "medium", "speed": "medium"},
    "kling_pro": {"name": "Kling Pro", "quality": "high", "speed": "medium"},
    "kling_v2": {"name": "Kling v2", "quality": "medium", "speed": "fast"},
    "sora_v2": {"name": "Sora v2", "quality": "high", "speed": "slow"},
    "sora_v2_pro": {"name": "Sora v2 Pro", "quality": "highest", "speed": "slow"},
    "runway_gen4": {"name": "Runway Gen-4", "quality": "high", "speed": "medium"},
    "seedance_lite": {"name": "Seedance Lite (1.x)", "quality": "medium", "speed": "fast"},
    "seedance_pro": {"name": "Seedance Pro (1.x)", "quality": "high", "speed": "medium"},
    "ltx_distilled": {"name": "LTX Distilled", "quality": "low", "speed": "fastest"},
}

LTX2_FRAME_COUNTS = {
    "1s": 25,
    "2s": 49,
    "3s": 73,
    "4s": 97,
    "5s": 121,
    "6.7s": 161,
    "8s": 193,
}


def estimate_quality_cost(quality: str) -> float:
    return {"highest": 0.50, "high": 0.35, "low": 0.15}.get(quality, 0.20)


def estimate_speed_runtime(speed: str) -> float:
    return {"fastest": 30.0, "fast": 60.0, "medium": 120.0, "slow": 300.0}.get(speed, 120.0)


def load_reference_image(inputs: dict[str, Any], width: int, height: int):
    from io import BytesIO

    import requests
    from PIL import Image

    ref_path = inputs.get("reference_image_path")
    ref_url = inputs.get("reference_image_url")
    if ref_path:
        image = Image.open(ref_path).convert("RGB")
    elif ref_url:
        response = requests.get(ref_url, timeout=60)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
    else:
        return ToolResult(
            success=False,
            error="image_to_video requires reference_image_url or reference_image_path",
        )
    return image.resize((width, height), Image.LANCZOS)


def poll_heygen(execution_id: str, api_key: str, timeout: int = 600) -> str:
    import requests

    headers = {"X-Api-Key": api_key}
    url = f"https://api.heygen.com/v1/workflows/executions/{execution_id}"
    deadline = time.time() + timeout
    interval = 5.0
    while time.time() < deadline:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json().get("data", {})
        status = data.get("status", "")
        if status == "completed":
            video_url = (
                data.get("output", {}).get("video", {}).get("video_url")
                or data.get("output", {}).get("video_url")
            )
            if video_url:
                return video_url
            raise RuntimeError(f"Completed but no video_url in output: {data}")
        if status in {"failed", "error"}:
            raise RuntimeError(f"HeyGen generation failed: {data.get('error', 'Unknown')}")
        time.sleep(min(interval, max(0.0, deadline - time.time())))
        interval = min(interval * 1.2, 30.0)
    raise TimeoutError(f"HeyGen execution {execution_id} timed out after {timeout}s")


def upload_image_fal(image_path: str) -> str:
    """Upload a local image to fal.ai storage and return a public URL."""
    import requests

    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")
    if not api_key:
        raise RuntimeError("FAL_KEY or FAL_AI_API_KEY required for image upload")
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    content_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
    init_resp = requests.post(
        "https://rest.alpha.fal.ai/storage/upload/initiate",
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json={"content_type": content_type, "file_name": path.name},
        timeout=30,
    )
    init_resp.raise_for_status()
    data = init_resp.json()
    put_resp = requests.put(
        data["upload_url"],
        headers={"Content-Type": content_type},
        data=path.read_bytes(),
        timeout=60,
    )
    put_resp.raise_for_status()
    return data["file_url"]


def upload_image_heygen(image_path: str, api_key: str) -> str:
    """Upload a local image to HeyGen, falling back to fal.ai storage."""
    import requests

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    try:
        response = requests.post(
            "https://api.heygen.com/v2/assets/upload",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={"content_type": "image/png", "file_name": path.name},
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json().get("data", {})
            upload_url = data.get("upload_url")
            file_url = data.get("url") or data.get("file_url")
            if upload_url and file_url:
                put_response = requests.put(
                    upload_url,
                    headers={"Content-Type": "image/png"},
                    data=path.read_bytes(),
                    timeout=60,
                )
                put_response.raise_for_status()
                return file_url
    except Exception:
        pass
    return upload_image_fal(image_path)


def generate_heygen_video(inputs: dict[str, Any]) -> ToolResult:
    import requests

    api_key = os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        return ToolResult(success=False, error="HEYGEN_API_KEY not set.")
    provider = inputs.get("provider_variant", "veo_3_1")
    if provider not in HEYGEN_PROVIDERS:
        return ToolResult(
            success=False,
            error=f"Unknown provider_variant: {provider}. Available: {', '.join(sorted(HEYGEN_PROVIDERS))}",
        )
    prompt = inputs["prompt"]
    aspect_ratio = inputs.get("aspect_ratio", "16:9")
    operation = inputs.get("operation", "text_to_video")
    workflow_input: dict[str, Any] = {
        "prompt": prompt,
        "provider": provider,
        "aspect_ratio": aspect_ratio,
    }
    if operation == "image_to_video":
        ref_url = inputs.get("reference_image_url")
        if inputs.get("reference_image_path") and not ref_url:
            ref_url = upload_image_heygen(inputs["reference_image_path"], api_key)
        if not ref_url:
            return ToolResult(
                success=False,
                error="image_to_video requires reference_image_url or reference_image_path",
            )
        workflow_input["reference_image_url"] = ref_url
    response = requests.post(
        "https://api.heygen.com/v1/workflows/executions",
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        json={"workflow_type": "GenerateVideoNode", "input": workflow_input},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    execution_id = payload.get("data", {}).get("execution_id")
    if not execution_id:
        return ToolResult(success=False, error=f"No execution_id in response: {payload}")
    video_url = poll_heygen(execution_id, api_key, timeout=600)
    output_path = Path(inputs.get("output_path", f"heygen_video_{execution_id}.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download = requests.get(video_url, timeout=120)
    download.raise_for_status()
    output_path.write_bytes(download.content)
    return ToolResult(
        success=True,
        data={
            "provider": "heygen",
            "provider_variant": provider,
            "provider_name": HEYGEN_PROVIDERS[provider]["name"],
            "mode": "api",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "operation": operation,
            "execution_id": execution_id,
            "output": str(output_path),
            "format": "mp4",
        },
        artifacts=[str(output_path)],
        model=provider,
    )


def generate_ltx_modal_video(inputs: dict[str, Any]) -> ToolResult:
    import base64

    import requests

    endpoint_url = os.environ.get("MODAL_LTX2_ENDPOINT_URL")
    if not endpoint_url:
        return ToolResult(success=False, error="MODAL_LTX2_ENDPOINT_URL not set.")
    prompt = inputs["prompt"]
    operation = inputs.get("operation", "text_to_video")
    aspect = inputs.get("aspect_ratio", "16:9")
    width = inputs.get("width")
    height = inputs.get("height")
    if width is None or height is None:
        width, height = {"16:9": (1024, 576), "9:16": (576, 1024)}.get(aspect, (512, 512))
    num_frames = inputs.get("num_frames", LTX2_FRAME_COUNTS.get(inputs.get("duration_hint", "5s"), 121))
    if (num_frames - 1) % 8 != 0:
        num_frames = ((num_frames - 1) // 8) * 8 + 1
    payload: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "fps": 24,
        "steps": inputs.get("num_inference_steps", 30),
        "negative_prompt": "worst quality, low quality, blurry, distorted, watermark, text, logo",
    }
    if inputs.get("seed") is not None:
        payload["seed"] = inputs["seed"]
    if operation == "image_to_video":
        ref_path = inputs.get("reference_image_path")
        ref_url = inputs.get("reference_image_url")
        if ref_path:
            payload["input_image"] = base64.b64encode(Path(ref_path).read_bytes()).decode()
        elif ref_url:
            payload["input_image_url"] = ref_url
        else:
            return ToolResult(
                success=False,
                error="image_to_video requires reference_image_url or reference_image_path",
            )
    response = requests.post(endpoint_url, json=payload, timeout=300)
    response.raise_for_status()
    output_path = Path(inputs.get("output_path", "ltx_video_modal.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content_type = response.headers.get("content-type", "")
    if "video" in content_type or "octet-stream" in content_type:
        output_path.write_bytes(response.content)
    else:
        response_payload = response.json()
        video_url = response_payload.get("video_url") or response_payload.get("url")
        if not video_url:
            return ToolResult(success=False, error=f"No video data in response: {response_payload}")
        download = requests.get(video_url, timeout=120)
        download.raise_for_status()
        output_path.write_bytes(download.content)
    return ToolResult(
        success=True,
        data={
            "provider": "ltx-modal",
            "provider_name": "LTX-2 (Modal)",
            "mode": "modal",
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "fps": 24,
            "duration_seconds": round(num_frames / 24, 2),
            "operation": operation,
            "output": str(output_path),
            "format": "mp4",
        },
        artifacts=[str(output_path)],
        seed=inputs.get("seed"),
        model="ltx-2",
    )


def probe_output(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"file_size_bytes": path.stat().st_size}
    if not shutil.which("ffprobe"):
        return info
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        import json

        info["ffprobe"] = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return info
