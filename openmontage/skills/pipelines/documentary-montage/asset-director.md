# Asset Director - Documentary Montage Pipeline

## When To Use

The shot list exists. Find the clips that fill each slot, download them,
inspect the candidates, and produce an `asset_manifest` with provenance.
OpenMontage uses direct stock-provider APIs for this stage; there is no local
embedding model, corpus index, or GPU retrieval path.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifact | `state.artifacts["scene_plan"]["scene_plan"]` | Slot descriptions, queries, and preferred sources |
| Prior artifact | `state.artifacts["idea"]["brief"]` | Era, source, and music constraints |
| Tool | `direct_clip_search` | Multi-provider API search and download |
| Tool (optional) | `music_gen`, user's `music_library/` | Music bed |

## Process

### 1. Search Through Provider APIs

Use `direct_clip_search` with one or more concrete queries per slot:

```python
direct_clip_search.execute({
    "output_dir": "projects/<name>/assets/video/raw_act2",
    "queries": [
        {"query": "cesium atomic clock laboratory", "slot_id": "slot_01"},
        {"query": "laser beam laboratory optics", "slot_id": "slot_02"},
    ],
    "sources": ["pexels", "pixabay_video", "archive_org"],
    "clips_per_query": 3,
    "filters": {
        "min_duration": 3,
        "max_duration": 40,
        "orientation": "landscape",
        "min_width": 1280,
    },
})
```

Provider API keys remain server-side in the environment. Never put provider
keys in the generation payload or asset manifest.

### 2. Inspect and Select

Inspect `<output_dir>/thumbnails/` and select exactly one clip per slot.
Prefer concrete visual matches over semantic guesses. Reject duplicates,
missing provenance, unsuitable duration, and clips that violate the brief's
era or source constraints.

When producing acts incrementally, reuse already downloaded files after
checking that their provenance and visual match still satisfy the new slot.
Run a targeted `direct_clip_search` request for gaps.

### 3. Children's / Fairy-Tale Content

For children's or fairy-tale briefs, route all searches to
`pixabay_video`, use explicit fantasy terms, and reject real-footage results
when the brief requires a consistent illustrated or magical style.

### 4. Record the Asset Manifest

Every selected asset must include:

- the slot ID and local file path,
- provider and original URL,
- license/provenance information,
- duration and dimensions when available,
- a short rejection log for plausible but unused candidates.

Set `source_tool` to `direct_clip_search` and record `metadata.search_stats`.
Do not emit `corpus_stats`, embedding paths, CLIP scores, or references to
local retrieval tools.

## Quality Gate

- Every scene slot has exactly one selected clip.
- No clip is reused for two slots unless the brief explicitly permits it.
- Every selected clip has provider, URL, and license provenance.
- Thumbnails were inspected and weak matches were replaced or logged.
- `metadata.search_stats` is present.
- All referenced asset files exist on disk.

## Common Pitfalls

- Treating provider search results as automatically correct without visual review.
- Calling adapter classes directly instead of `direct_clip_search`.
- Storing API keys in JSON, artifacts, or logs.
- Reusing a clip without recording the cross-act decision.
- Adding generated footage to a documentary montage unless the brief explicitly
  asks for it.
