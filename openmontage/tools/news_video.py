"""Local-first bilingual news-video workflow built from Google provider tools.

The tool deliberately separates planning from rendering. ``plan`` creates a
reviewable local manifest with no provider calls; ``render`` follows the
requested visual mode, synthesizes a separate narration track, and composes
the result locally. Strict ``text_to_video`` and ``image_to_video`` modes do
not silently fall back to Imagen.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openmontage.tools.audio.google_tts import GoogleTTS
from openmontage.tools.base_tool import (
    BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy,
    ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier,
)
from openmontage.tools.graphics.google_imagen import GoogleImagen
from openmontage.tools.video.veo_video import VeoVideo
from openmontage.tools.video.video_compose import VideoCompose


@dataclass(frozen=True)
class NewsPreset:
    profile: str
    aspect_ratio: str
    width: int
    height: int
    duration_seconds: int


PRESETS = {
    "tiktok": NewsPreset("tiktok", "9:16", 1080, 1920, 60),
    "youtube": NewsPreset("youtube_landscape", "16:9", 1920, 1080, 180),
}

LANGUAGES = {
    "vi": {"code": "vi-VN", "voice": "Kore", "wpm": 130},
    "en": {"code": "en-US", "voice": "Kore", "wpm": 145},
}


class NewsVideo(BaseTool):
    """Create a local TikTok or YouTube news explainer from cited source text."""

    name = "news_video"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "news_video"
    provider = "google"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = ["cmd:ffmpeg", "env:GOOGLE_API_KEY"]
    install_instructions = "Set GOOGLE_API_KEY and enable the Google APIs used by Imagen, Veo, and Cloud Text-to-Speech."
    # These are the only public generation operations.  Narration and
    # composition remain internal implementation details of this workflow.
    capabilities = ["text_to_image", "text_to_video", "image_to_video"]
    supports = {
        "languages": ["vi", "en"],
        "presets": list(PRESETS),
        "publishing": False,
        "internal_support": ["google_tts", "video_compose"],
    }
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["rate_limit", "timeout"])
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=5000, network_required=True)
    side_effects = ["writes a local review package and, in render mode, calls Google media APIs"]

    input_schema = {
        "type": "object",
        "required": ["title", "source_text", "sources", "language", "preset", "output_dir"],
        "properties": {
            "operation": {"type": "string", "enum": ["plan", "render"], "default": "plan"},
            "title": {"type": "string"},
            "source_text": {"type": "string", "description": "Verified source dossier or approved narration."},
            "sources": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "script": {"type": "string", "description": "Optional approved narration; avoids automatic shortening."},
            "language": {"type": "string", "enum": ["vi", "en"]},
            "voice": {"type": "string", "description": "Optional Google Cloud TTS voice override."},
            "preset": {"type": "string", "enum": ["tiktok", "youtube"]},
            "output_dir": {"type": "string"},
            "motion_scene_count": {"type": "integer", "minimum": 0, "maximum": 6, "default": 3},
            "text_to_video_scene_count": {"type": "integer", "minimum": 0, "maximum": 2, "default": 1},
            "visual_mode": {"type": "string", "enum": ["mixed", "text_to_video", "image_to_video"], "default": "mixed"},
            "reference_image_path": {"type": "string", "description": "Optional local image used by image_to_video scenes."},
            "image_model": {"type": "string", "default": "gemini-3.1-flash-image", "description": "Google image model used for still scenes."},
            "video_model": {"type": "string", "default": "veo3.1-lite", "description": "Google Veo model id or supported alias used for motion scenes."},
            "visual_style": {"type": "string", "default": "clean editorial news illustration, documentary b-roll, no text in image"},
        },
    }

    def get_status(self) -> ToolStatus:
        tools = (GoogleImagen(), GoogleTTS(), VeoVideo(), VideoCompose())
        return ToolStatus.AVAILABLE if all(tool.get_status() == ToolStatus.AVAILABLE for tool in tools) else ToolStatus.UNAVAILABLE

    @staticmethod
    def _safe_slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug[:48] or "news-video"

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", text.strip()) if s.strip()]

    def _script(self, inputs: dict[str, Any], target_seconds: int) -> str:
        if inputs.get("script"):
            return str(inputs["script"]).strip()
        max_words = int(target_seconds * LANGUAGES[inputs["language"]]["wpm"] / 60)
        words: list[str] = []
        for sentence in self._sentences(inputs["source_text"]):
            candidate = sentence.split()
            if words and len(words) + len(candidate) > max_words:
                break
            words.extend(candidate)
        if not words:
            raise ValueError("source_text must contain narration-ready text or provide script.")
        return " ".join(words)

    def _scene_plan(self, script: str, preset: NewsPreset, style: str, motion_count: int, t2v_count: int, visual_mode: str = "mixed") -> list[dict[str, Any]]:
        sentences = self._sentences(script)
        count = max(1, math.ceil(preset.duration_seconds / 8))
        groups = ["" for _ in range(count)]
        for index, sentence in enumerate(sentences):
            groups[min(count - 1, index * count // max(1, len(sentences)))] += (" " if groups[min(count - 1, index * count // max(1, len(sentences)))] else "") + sentence
        scenes = []
        remaining = preset.duration_seconds
        for index, narration in enumerate(groups):
            duration = min(8, remaining)
            remaining -= duration
            scene_mode = "still"
            if visual_mode == "text_to_video":
                scene_mode = "text_to_video"
            elif visual_mode == "image_to_video":
                scene_mode = "image_to_video"
            elif visual_mode == "mixed":
                if index < min(t2v_count, motion_count):
                    scene_mode = "text_to_video"
                elif index < motion_count:
                    scene_mode = "image_to_video"
            scenes.append({
                "id": f"scene-{index + 1:02d}", "duration_seconds": duration,
                "narration": narration or script, "visual_mode": scene_mode,
                "prompt": f"{style}. Editorial visual for: {narration or script}. No logos, no captions, no depiction of a real person unless supplied in source media.",
            })
        return scenes

    @staticmethod
    def _estimate_cost(script: str, scenes: list[dict[str, Any]], *, has_reference_image: bool = False) -> float:
        """Estimate only the provider work this workflow will request."""
        generated_image_count = sum(
            scene["visual_mode"] == "still"
            or (scene["visual_mode"] == "image_to_video" and not has_reference_image)
            for scene in scenes
        )
        image_cost = GoogleImagen().estimate_cost({"number_of_images": generated_image_count}) if generated_image_count else 0.0
        motion_cost = sum(
            VeoVideo().estimate_cost({"backend": "google", "duration": "8s"})
            for scene in scenes
            if scene["visual_mode"] in {"text_to_video", "image_to_video"}
        )
        voice_cost = GoogleTTS().estimate_cost({"text": script})
        return round(image_cost + motion_cost + voice_cost, 4)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _timestamp(seconds: float) -> str:
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3_600_000)
        minutes, milliseconds = divmod(milliseconds, 60_000)
        whole, milliseconds = divmod(milliseconds, 1000)
        return f"{hours:02}:{minutes:02}:{whole:02},{milliseconds:03}"

    def _write_srt(self, script: str, total_seconds: float, path: Path) -> None:
        words = script.split()
        chunks = [" ".join(words[i:i + 10]) for i in range(0, len(words), 10)] or [script]
        span = total_seconds / len(chunks)
        lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            lines += [str(index), f"{self._timestamp((index - 1) * span)} --> {self._timestamp(index * span)}", chunk, ""]
        path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _audio_duration(path: Path, fallback: float) -> float:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, check=False)
        try:
            return max(0.1, float(probe.stdout.strip()))
        except ValueError:
            return fallback

    @staticmethod
    def _run_ffmpeg(command: list[str]) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-800:]}")

    def _still_clip(self, image: Path, output: Path, duration: float, preset: NewsPreset) -> None:
        filter_graph = (
            f"scale={preset.width}:{preset.height}:force_original_aspect_ratio=increase,"
            f"crop={preset.width}:{preset.height},fps=30,format=yuv420p"
        )
        self._run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-t", str(duration), "-vf", filter_graph, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output)])

    def _render(self, manifest: dict[str, Any], root: Path, inputs: dict[str, Any]) -> ToolResult:
        preset = PRESETS[inputs["preset"]]
        assets = root / "assets"
        assets.mkdir(exist_ok=True)
        imagen, veo, tts = GoogleImagen(), VeoVideo(), GoogleTTS()
        image_model = str(inputs.get("image_model") or "gemini-3.1-flash-image")
        video_model = str(inputs.get("video_model") or "veo3.1-lite")
        clips: list[Path] = []
        for scene in manifest["scenes"]:
            image_path = assets / f"{scene['id']}.png"
            reference_image = inputs.get("reference_image_path")
            if scene["visual_mode"] == "image_to_video" and reference_image:
                shutil.copy2(reference_image, image_path)
            elif scene["visual_mode"] in {"still", "image_to_video"}:
                image_result = imagen.execute({"prompt": scene["prompt"], "aspect_ratio": preset.aspect_ratio, "model": image_model, "output_path": str(image_path)})
                if not image_result.success:
                    return image_result
            clip_path = assets / f"{scene['id']}.mp4"
            if scene["visual_mode"] == "text_to_video":
                video_result = veo.execute({"backend": "google", "operation": "text_to_video", "model_variant": video_model, "prompt": scene["prompt"], "duration": "8s", "aspect_ratio": preset.aspect_ratio, "resolution": "1080p", "generate_audio": False, "output_path": str(clip_path)})
                if not video_result.success:
                    return video_result
            elif scene["visual_mode"] == "image_to_video":
                if not image_path.is_file():
                    return ToolResult(success=False, error="image_to_video requires reference_image_path.")
                video_result = veo.execute({"backend": "google", "operation": "image_to_video", "model_variant": video_model, "image_path": str(image_path), "prompt": scene["prompt"], "duration": "8s", "aspect_ratio": preset.aspect_ratio, "resolution": "1080p", "generate_audio": False, "output_path": str(clip_path)})
                if not video_result.success:
                    return video_result
            else:
                self._still_clip(image_path, clip_path, scene["duration_seconds"], preset)
            scene["image_path"] = str(image_path) if image_path.is_file() else None
            scene["clip_path"] = str(clip_path)
            clips.append(clip_path)

        narration = root / "narration.wav"
        language = LANGUAGES[inputs["language"]]
        audio_result = tts.execute({"backend": "gemini", "text": manifest["script"], "voice": inputs.get("voice") or language["voice"], "language_code": language["code"], "audio_encoding": "LINEAR16", "output_path": str(narration)})
        if not audio_result.success:
            return audio_result
        total_duration = self._audio_duration(narration, preset.duration_seconds)
        subtitle = root / "captions.srt"
        self._write_srt(manifest["script"], total_duration, subtitle)
        cuts, cursor = [], 0.0
        for scene in manifest["scenes"]:
            duration = min(scene["duration_seconds"], max(0.1, total_duration - cursor))
            if duration <= 0.1:
                break
            cuts.append({"source": scene["clip_path"], "in_seconds": 0, "out_seconds": duration})
            cursor += duration
        final_path = root / "final.mp4"
        composed = VideoCompose().execute({"operation": "compose", "edit_decisions": {"cuts": cuts, "metadata": {"compose_target": {"width": preset.width, "height": preset.height, "fit": "cover"}}}, "audio_path": str(narration), "subtitle_path": str(subtitle), "profile": preset.profile, "output_path": str(final_path)})
        if not composed.success:
            return composed
        manifest["render"] = {"audio_path": str(narration), "subtitle_path": str(subtitle), "output_path": str(final_path), "actual_audio_seconds": total_duration}
        self._write_json(root / "manifest.json", manifest)
        return ToolResult(success=True, data=manifest["render"], artifacts=[str(final_path), str(subtitle), str(root / "manifest.json")])

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            preset = PRESETS[inputs["preset"]]
            root = Path(inputs["output_dir"]).expanduser().resolve() / self._safe_slug(inputs["title"])
            root.mkdir(parents=True, exist_ok=True)
            script = self._script(inputs, preset.duration_seconds)
            visual_mode = inputs.get("visual_mode", "mixed")
            if visual_mode == "image_to_video" and not inputs.get("reference_image_path"):
                raise ValueError("image_to_video requires reference_image_path.")
            scenes = self._scene_plan(script, preset, inputs.get("visual_style", "editorial news visual"), int(inputs.get("motion_scene_count", 3)), int(inputs.get("text_to_video_scene_count", 1)), visual_mode)
            manifest = {"title": inputs["title"], "language": inputs["language"], "preset": inputs["preset"], "preset_details": asdict(preset), "sources": inputs["sources"], "script": script, "scenes": scenes, "estimated_cost_usd": self._estimate_cost(script, scenes, has_reference_image=bool(inputs.get("reference_image_path"))), "publishing": {"enabled": False, "destination": "local_only"}}
            manifest_path = root / "manifest.json"
            self._write_json(manifest_path, manifest)
            if inputs.get("operation", "plan") == "plan":
                return ToolResult(success=True, data={"manifest": str(manifest_path), "scene_count": len(scenes), "estimated_motion_clips": min(len(scenes), int(inputs.get("motion_scene_count", 3))), "estimated_cost_usd": manifest["estimated_cost_usd"]}, artifacts=[str(manifest_path)])
            return self._render(manifest, root, inputs)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
