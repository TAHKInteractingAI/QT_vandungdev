"""Background removal through the fal.ai Imageutils API."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from openmontage.tools.base_tool import (
    BaseTool,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class BgRemove(BaseTool):
    name = "bg_remove"
    version = "0.2.0"
    tier = ToolTier.ENHANCE
    capability = "enhancement"
    provider = "fal"
    stability = ToolStability.BETA
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Set FAL_KEY or FAL_AI_API_KEY. The input image is uploaded to fal.ai "
        "before background removal."
    )
    agent_skills = ["bfl-api"]

    capabilities = ["background_removal", "alpha_matte", "custom_background"]
    supports = {
        "offline": False,
        "custom_background": True,
        "crop_to_bbox": True,
    }
    best_for = ["API background removal for images"]
    not_good_for = ["offline processing", "video background removal"]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string", "description": "Path to input image"},
            "output_path": {"type": "string"},
            "bg_color": {
                "type": "string",
                "description": "Optional local composite background color, e.g. #FFFFFF",
            },
            "crop_to_bbox": {"type": "boolean", "default": False},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=True
    )
    idempotency_key_fields = ["input_path", "bg_color", "crop_to_bbox"]
    side_effects = [
        "uploads an input image to fal.ai",
        "calls fal.ai background-removal API",
        "writes the returned PNG to output_path",
    ]
    user_visible_verification = ["Inspect the cutout edges and transparency"]

    @staticmethod
    def _api_key() -> str | None:
        return os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._api_key() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        input_path = Path(str(inputs.get("input_path", ""))).expanduser()
        if not input_path.exists():
            return ToolResult(success=False, error=f"Input not found: {input_path}")

        api_key = self._api_key()
        if not api_key:
            return ToolResult(success=False, error=self.install_instructions)

        if inputs.get("alpha_matting"):
            return ToolResult(
                success=False,
                error="alpha_matting is not supported by the selected fal.ai API model.",
            )

        import requests

        started = time.time()
        try:
            from openmontage.tools.video._shared import upload_image_fal

            image_url = str(inputs.get("image_url") or upload_image_fal(str(input_path)))
            response = requests.post(
                "https://fal.run/fal-ai/imageutils/rembg",
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "image_url": image_url,
                    "crop_to_bbox": bool(inputs.get("crop_to_bbox", False)),
                },
                timeout=180,
            )
            response.raise_for_status()
            image_info = response.json().get("image") or {}
            result_url = image_info.get("url")
            if not result_url:
                raise RuntimeError("fal.ai response did not include image.url")

            image_response = requests.get(result_url, timeout=120)
            image_response.raise_for_status()
            output_path = Path(
                str(
                    inputs.get(
                        "output_path",
                        input_path.with_name(f"{input_path.stem}_nobg.png"),
                    )
                )
            ).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_response.content)

            if inputs.get("bg_color"):
                from PIL import Image

                with Image.open(output_path).convert("RGBA") as foreground:
                    background = Image.new(
                        "RGBA", foreground.size, str(inputs["bg_color"])
                    )
                    background.alpha_composite(foreground)
                    background.convert("RGB").save(output_path)
        except Exception as exc:
            return ToolResult(success=False, error=f"fal.ai background removal failed: {exc}")

        return ToolResult(
            success=True,
            data={
                "provider": "fal",
                "model": "fal-ai/imageutils/rembg",
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - started, 2),
        )
