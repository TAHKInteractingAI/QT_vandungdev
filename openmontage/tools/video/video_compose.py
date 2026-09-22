"""Small FFmpeg-only assembler for generated clips.

Generation belongs to Veo/Imagen. This tool only joins finished clips,
normalizes the output profile, adds narration, and burns an optional SRT.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from openmontage.tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ResumeSupport,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


class VideoCompose(BaseTool):
    name = "video_compose"
    version = "0.2.0"
    tier = ToolTier.CORE
    capability = "video_post"
    provider = "ffmpeg"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install FFmpeg: https://ffmpeg.org/download.html"
    agent_skills = ["ffmpeg"]
    capabilities = ["compose_cuts", "burn_subtitles", "encode_profile"]
    supports = {
        "audio_mux": True,
        "subtitle_burn": True,
        "aspect_ratio_profiles": True,
    }
    best_for = [
        "joining generated video clips",
        "adding local narration and SRT captions",
        "fixed TikTok/YouTube output profiles",
    ]
    not_good_for = ["interactive editing", "React composition", "source-video editing UI"]
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["FFmpeg error"])
    resume_support = ResumeSupport.FROM_START
    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=5000, network_required=False
    )
    idempotency_key_fields = ["operation", "edit_decisions", "audio_path", "subtitle_path"]
    side_effects = ["writes video file to output_path"]
    user_visible_verification = ["Play the final video and verify narration, captions, duration, and aspect ratio"]

    input_schema = {
        "type": "object",
        "required": ["operation", "edit_decisions"],
        "properties": {
            "operation": {"type": "string", "enum": ["compose"]},
            "edit_decisions": {"type": "object", "description": "Cuts and optional compose_target metadata."},
            "audio_path": {"type": "string"},
            "subtitle_path": {"type": "string"},
            "subtitle_style": {"type": "object"},
            "profile": {"type": "string", "description": "Output profile, such as tiktok or youtube_landscape."},
            "output_path": {"type": "string", "default": "composed_output.mp4"},
            "codec": {"type": "string", "default": "libx264"},
            "crf": {"type": "integer", "default": 23},
            "preset": {"type": "string", "default": "medium"},
        },
    }

    @staticmethod
    def _is_image(path: Path) -> bool:
        return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}

    @staticmethod
    def _build_atempo(speed: float) -> str:
        """Build an FFmpeg atempo chain, whose accepted range is 0.5..2.0."""
        speed = float(speed)
        if speed <= 0:
            raise ValueError("speed must be greater than zero")
        filters: list[str] = []
        while speed > 2.0:
            filters.append("atempo=2.0")
            speed /= 2.0
        while speed < 0.5:
            filters.append("atempo=0.5")
            speed /= 0.5
        filters.append(f"atempo={speed:g}")
        return ",".join(filters)

    @staticmethod
    def _has_audio_stream(path: Path) -> bool:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())

    @staticmethod
    def _subtitle_style(style: dict[str, Any]) -> str:
        values = {
            "FontName": style.get("font", "Arial"),
            "FontSize": style.get("font_size", 24),
            "PrimaryColour": style.get("primary_color", "&HFFFFFF"),
            "OutlineColour": style.get("outline_color", "&H000000"),
            "Outline": style.get("outline_width", 2),
            "Alignment": style.get("alignment", 2),
            "MarginV": style.get("margin_v", 40),
        }
        return ",".join(f"{key}={value}" for key, value in values.items())

    @staticmethod
    def _target(edit_decisions: dict[str, Any], profile_name: str | None) -> tuple[int, int, str]:
        width, height, fit = 1920, 1080, "pad"
        target = (edit_decisions.get("metadata") or {}).get("compose_target")
        if isinstance(target, dict):
            width = int(target.get("width", width))
            height = int(target.get("height", height))
            fit = target.get("fit", fit) if target.get("fit") in {"pad", "cover"} else fit
        if profile_name:
            from openmontage.lib.media_profiles import get_profile
            profile = get_profile(profile_name)
            width, height = profile.width, profile.height
        return width, height, fit

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        if inputs.get("operation") != "compose":
            return ToolResult(success=False, error="Only operation='compose' is supported.")
        try:
            result = self._compose(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
        result.duration_seconds = round(time.time() - started, 2)
        return result

    def _compose(self, inputs: dict[str, Any]) -> ToolResult:
        edit_decisions = inputs.get("edit_decisions") or {}
        cuts = edit_decisions.get("cuts") or []
        if not cuts:
            return ToolResult(success=False, error="No cuts in edit_decisions")

        output_path = Path(inputs.get("output_path", "composed_output.mp4"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        profile_name = inputs.get("profile")
        width, height, fit = self._target(edit_decisions, profile_name)
        codec = inputs.get("codec", "libx264")
        crf = inputs.get("crf", 23)
        preset = inputs.get("preset", "medium")
        temp_dir = output_path.parent / ".compose_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_segments: list[Path] = []
        concat_path = temp_dir / "concat_list.txt"
        concat_output = temp_dir / "concat.mp4"

        try:
            for index, cut in enumerate(cuts):
                source = Path(cut["source"])
                if not source.is_file():
                    return ToolResult(success=False, error=f"Cut source not found: {source}")
                if self._is_image(source):
                    return ToolResult(success=False, error="Image cuts must be converted to video before compose.")

                start = float(cut.get("in_seconds", 0))
                end = float(cut.get("out_seconds", start))
                duration = end - start
                if duration <= 0:
                    return ToolResult(success=False, error=f"Invalid cut duration for {source}")
                speed = float(cut.get("speed", 1.0))
                segment = temp_dir / f"seg_{index:04d}.mp4"
                geometry = (
                    [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}"]
                    if fit == "cover"
                    else [f"scale={width}:{height}:force_original_aspect_ratio=decrease", f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"]
                )
                video_filters = [*geometry, "setsar=1", "fps=30"]
                audio_filters: list[str] = []
                if speed != 1.0:
                    video_filters.append(f"setpts={1.0 / speed}*PTS")
                    audio_filters.append(self._build_atempo(speed))

                command = ["ffmpeg", "-y", "-ss", str(start), "-t", str(duration), "-i", str(source)]
                if self._has_audio_stream(source):
                    command += ["-filter:v", ",".join(video_filters)]
                    if audio_filters:
                        command += ["-filter:a", ",".join(audio_filters)]
                    command += ["-c:v", codec, "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
                else:
                    command += ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-filter:v", ",".join(video_filters)]
                    if audio_filters:
                        command += ["-filter:a", ",".join(audio_filters)]
                    command += ["-map", "0:v:0", "-map", "1:a:0", "-c:v", codec, "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
                self.run_command(command + [str(segment)])
                temp_segments.append(segment)

            concat_path.write_text("".join(f"file '{segment.resolve()}'\n" for segment in temp_segments), encoding="utf-8")
            self.run_command(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(concat_output)])

            subtitle_path = inputs.get("subtitle_path")
            if not subtitle_path:
                subtitle_path = (edit_decisions.get("subtitles") or {}).get("source")
            filters: list[str] = []
            if subtitle_path and Path(subtitle_path).is_file():
                escaped = str(Path(subtitle_path).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
                filters.append(f"subtitles='{escaped}':force_style='{self._subtitle_style(inputs.get('subtitle_style') or {})}'")

            audio_path = inputs.get("audio_path")
            command = ["ffmpeg", "-y", "-i", str(concat_output)]
            if audio_path and Path(audio_path).is_file():
                command += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-shortest"]
            else:
                command += ["-map", "0:v:0", "-map", "0:a:0", "-c:a", "copy"]
            if filters:
                command += ["-vf", ",".join(filters), "-c:v", codec, "-crf", str(crf), "-preset", preset]
            else:
                command += ["-c:v", "copy"]
            self.run_command(command + [str(output_path)])
            return ToolResult(
                success=True,
                data={"operation": "compose", "cut_count": len(cuts), "output": str(output_path), "profile": profile_name},
                artifacts=[str(output_path)],
            )
        finally:
            for path in temp_segments + [concat_path, concat_output]:
                if path.exists():
                    path.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass
