# OpenMontage Agent Guide

OpenMontage is an API-first local video generator. Keep the public surface small:

- `text_to_image` -> Google Imagen
- `text_to_video` -> Google Veo 3.1 Lite by default
- `image_to_video` -> Google Veo 3.1 Lite by default

Narration is an internal Gemini TTS step. Final assembly is an internal FFmpeg
step that joins generated clips, adds narration, burns optional SRT captions,
and writes a fixed TikTok (`9:16`) or YouTube (`16:9`) file locally. Publishing
is outside this repository.

## Runtime rules

1. Use `tools/news_video.py` for the bilingual news-video workflow.
2. Use `tools/video/veo_video.py` for video generation.
3. Use `tools/graphics/google_imagen.py` for still-image generation.
4. Use `tools/audio/google_tts.py` for Vietnamese or English narration.
5. Use `tools/video/video_compose.py` only for local FFmpeg composition.
6. Keep API keys in `.env`; never commit secrets.
7. Outputs belong under the caller's local `output_dir`.

## Product contract

- Languages: `vi`, `en`.
- Output profiles: `tiktok` (`1080x1920`) and `youtube` (`1920x1080`).
- The `plan` operation must not call external providers.
- The `render` operation may call Google APIs and must save the final artifact locally.
- No source-footage editing, video trimming, Remotion, HyperFrames, publishing,
  or alternate composition engines are part of the active product.

## Verification

From this directory:

```bash
.venv/bin/python main.py
PYTHONPATH=openmontage .venv/bin/python -c "from tools.tool_registry import registry; import json; print(json.dumps(registry.public_media_menu(), indent=2))"
.venv/bin/python -m py_compile openmontage/tools/base_tool.py openmontage/tools/tool_registry.py openmontage/tools/news_video.py
```

The public-media menu is the source of truth for the currently configured API
surface. It should show the three public operations plus internal narration and
composition support.
