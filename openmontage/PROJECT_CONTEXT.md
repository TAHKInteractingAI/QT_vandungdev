# OpenMontage - Shared Project Context

OpenMontage is a portable, API-first backend for generating narrated short
videos. The agent drives the workflow; Python supplies provider adapters,
local persistence, and FFmpeg composition.

## Active product surface

| Operation | Implementation |
|---|---|
| `text_to_image` | `tools/graphics/google_imagen.py` |
| `text_to_video` | `tools/video/veo_video.py` |
| `image_to_video` | `tools/video/veo_video.py` |

Internal-only services are `tools/audio/google_tts.py` and
`tools/video/video_compose.py`.

## Workflow

```text
approved source text
  -> local plan (script + scene manifest)
  -> Imagen stills / Veo clips
  -> Gemini TTS narration + SRT
  -> FFmpeg composition
  -> local TikTok or YouTube file
```

## Product constraints

- Languages: Vietnamese (`vi`) and English (`en`).
- Profiles: TikTok vertical `1080x1920`; YouTube landscape `1920x1080`.
- Default Veo model: `veo3.1-lite`.
- Outputs are local files only; there is no publishing integration.
- Remotion, HyperFrames, source-footage editing, trimming, and alternate
  composition engines are removed from the active runtime.

## Key files

| File | Purpose |
|---|---|
| `tools/tool_registry.py` | Registry and public media menu |
| `tools/news_video.py` | Bilingual news-video plan/render workflow |
| `tools/video/veo_video.py` | Veo text-to-video and image-to-video |
| `tools/video/video_compose.py` | FFmpeg-only clip/audio/caption assembly |
| `lib/media_profiles.py` | Fixed output profiles |
| `schemas/` | Artifact and tool contracts |
| `main.py` | Root entrypoint for the local server |

## Verification

Run the public-media menu command, Python compilation checks, and the direct
NewsVideo/FFmpeg smoke checks before changing the active runtime path.
