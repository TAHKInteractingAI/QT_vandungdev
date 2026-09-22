# Transcription Skill (Transcriber / Cloud STT)

## When to Use

Use the `transcriber` tool whenever you need to convert speech to text from
audio or video files. This is the entry point for all transcript-dependent
workflows: subtitle generation, edit decisions based on spoken content, and
scene analysis from dialogue.

While historically backed by local WhisperX inference, OpenMontage now routes
all transcription through high-precision Cloud STT APIs (Azure AI Speech and
DashScope ASR) with zero local GPU or PyTorch dependencies, producing exact
word-level timestamps and speaker diarization.

## Tool & Providers

| Tool | Capability | Default Provider | Alternate Provider |
|------|-----------|------------------|-------------------|
| `transcriber` | Speech-to-text with word timestamps, language detection, diarization | Azure AI Speech (`azure_stt`) | DashScope ASR (`dashscope_asr`) |

## How It Works

1. **Audio Extraction / Normalization:** Audio is extracted from the video or formatted to standard mono/stereo PCM or MP3 for cloud ingestion.
2. **Cloud API Dispatch:** The tool dispatches audio to Azure AI Speech Fast Transcription REST API (`azure_stt`) or Alibaba Cloud DashScope ASR (`dashscope_asr`), utilizing configured API credentials (`AZURE_SPEECH_KEY`, `DASHSCOPE_API_KEY`).
3. **Word-Level Alignment:** The cloud provider returns word-level timestamps and confidence scores natively, ensuring exact subtitle sync.
4. **Diarization (optional):** Cloud multi-speaker diarization assigns speaker labels without requiring local Hugging Face tokens or pyannote installation.

## Provider Configuration

| Provider | Credentials Required | Key Features |
|----------|----------------------|--------------|
| **Azure AI Speech** | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Fast transcription REST, candidate locale auto-detection, speaker diarization |
| **DashScope ASR** | `DASHSCOPE_API_KEY` | High-accuracy multilingual ASR (`qwen3-asr-flash-filetrans`), word-level timestamps |

## Key Patterns

### Choosing When to Diarize

- **Single speaker (talking head):** Skip diarization (`diarize: false`) — reduces latency and simplifies transcript output.
- **Multiple speakers (interview, podcast, panel):** Enable diarization (`diarize: true`) to label who said what across segments.

### Word Timestamps for Subtitles

The transcriber produces word-level timestamps with confidence scores. The `subtitle_gen` tool consumes these directly:

```json
{
  "word_timestamps": [
    {"word": "Hello", "start": 0.5, "end": 0.8, "probability": 0.95},
    {"word": "world", "start": 0.9, "end": 1.2, "probability": 0.92}
  ]
}
```

### Language Detection

- Pass `language: null` or omit to let the cloud provider auto-detect language across candidate locales.
- Pass an explicit ISO 639-1 / BCP-47 code (e.g. `en`, `zh-CN`, `ja`, `es`) when the spoken language is predetermined for faster and more accurate processing.

## Quality Checklist

- [ ] Transcript text is accurate (spot-check 3-5 segments)
- [ ] Word timestamps align with actual speech when played back
- [ ] No missing segments or large gaps in the transcript
- [ ] Language was correctly detected (if auto)
- [ ] Speaker labels are correct (if diarization was used)
- [ ] Cloud STT credentials (`AZURE_SPEECH_KEY` or `DASHSCOPE_API_KEY`) are active
