"""Backward-compatible API transcription alias.

The historical ``transcriber`` name is retained for pipeline compatibility,
but faster-whisper/WhisperX inference is removed. Audio is sent to Azure AI
Speech through the existing ``azure_stt`` adapter.
"""

from __future__ import annotations

from typing import Any

from openmontage.tools.analysis.azure_stt import AzureSpeechToText
from openmontage.tools.base_tool import (
    BaseTool,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class Transcriber(BaseTool):
    name = "transcriber"
    version = "0.2.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "azure"
    stability = ToolStability.BETA
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Local Whisper execution is disabled. Set AZURE_SPEECH_KEY and "
        "AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT."
    )
    fallback = "azure_stt"
    fallback_tools = ["azure_stt", "dashscope_asr"]
    agent_skills = ["azure-speech-to-text"]

    capabilities = ["speech_to_text", "word_timestamps", "multilingual"]
    supports = {
        "word_timestamps": True,
        "multilingual": True,
        "diarization": True,
        "offline": False,
    }
    best_for = ["legacy pipeline compatibility through Azure Speech API"]
    not_good_for = ["offline transcription"]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string"},
            "language": {"type": "string"},
            "diarize": {"type": "boolean", "default": False},
            "output_dir": {"type": "string"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "segments": {"type": "array"},
            "word_timestamps": {"type": "array"},
            "language": {"type": "string"},
            "duration_seconds": {"type": "number"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    idempotency_key_fields = ["input_path", "language", "diarize"]
    side_effects = ["sends audio to Azure AI Speech API", "writes transcript JSON"]
    user_visible_verification = [
        "Check transcript text against source audio",
        "Verify word timestamps align with speech",
    ]

    def get_status(self) -> ToolStatus:
        return AzureSpeechToText().get_status()

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return AzureSpeechToText().estimate_cost(inputs)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        return AzureSpeechToText().execute(dict(inputs))
