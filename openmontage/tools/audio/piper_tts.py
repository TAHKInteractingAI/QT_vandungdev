"""Backward-compatible API TTS alias.

The historical ``piper_tts`` name is retained for old pipeline manifests, but
local Piper inference is removed. Calls are delegated to Google TTS.
"""

from __future__ import annotations

from typing import Any

from openmontage.tools.audio.google_tts import GoogleTTS
from openmontage.tools.base_tool import (
    BaseTool,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class PiperTTS(BaseTool):
    name = "piper_tts"
    version = "0.2.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "google_tts"
    stability = ToolStability.EXPERIMENTAL
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Local Piper execution is disabled. Set GOOGLE_TTS_API_KEY, "
        "GOOGLE_API_KEY, GEMINI_API_KEY, or configure a Google service account."
    )
    fallback = "google_tts"
    fallback_tools = ["google_tts", "openai_tts", "elevenlabs_tts"]
    agent_skills = ["text-to-speech"]

    capabilities = ["text_to_speech"]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
    }
    best_for = ["legacy pipeline compatibility through Google TTS API"]
    not_good_for = ["offline narration", "privacy-sensitive local-only workflows"]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "voice": {"type": "string"},
            "language_code": {"type": "string", "default": "en-US"},
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    idempotency_key_fields = ["text", "voice", "language_code", "output_path"]
    side_effects = ["sends text to Google TTS API", "writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio for intelligibility"]

    def get_status(self) -> ToolStatus:
        return GoogleTTS().get_status()

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return GoogleTTS().estimate_cost(inputs)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        adapted = {
            "text": inputs["text"],
            "backend": "cloud",
            "voice": inputs.get("voice", "en-US-Neural2-D"),
            "language_code": inputs.get("language_code", "en-US"),
            "audio_encoding": "LINEAR16",
            "output_path": inputs.get("output_path", "tts_output.wav"),
        }
        return GoogleTTS().execute(adapted)
