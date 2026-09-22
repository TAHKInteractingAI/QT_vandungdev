"""Route the active OpenMontage video surface to Google Veo."""

from __future__ import annotations

from openmontage.tools.base_tool import BaseTool, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier


class VideoSelector(BaseTool):
    name = "video_selector"
    version = "0.3.1"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "selector"
    stability = ToolStability.BETA
    runtime = ToolRuntime.API
    agent_skills = ["ai-video-gen"]

    # Video generation never falls back to an image-only tool.
    # Default score gap for the preferred_provider override (see input_schema).
    PREFERRED_PROVIDER_GAP = 0.15

    capabilities = [
        "text_to_video", "image_to_video", "provider_selection",
    ]
    supports = {
        "user_preference_routing": True,
        "reference_image": True,
    }
    best_for = [
        "preflight routing",
        "user-facing recommendation flows",
        "Google Veo text-to-video and image-to-video routing",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "preferred_provider": {
                "type": "string",
                "description": "Provider name or 'auto'. Valid values are discovered at runtime from the registry.",
                "default": "auto",
            },
            "preferred_provider_gap": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "default": 0.15,
                "description": (
                    "Max weighted-score gap (0-1) within which an explicit preferred_provider "
                    "overrides the top-ranked provider. If the preferred provider's best score "
                    "falls more than this far below the overall top, the preference is ignored "
                    "and the top-ranked provider wins. Default 0.15 — honors a preference unless "
                    "it would drag selection to a drastically worse provider."
                ),
            },
            "allowed_providers": {"type": "array", "items": {"type": "string"}},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "rank"],
                "default": "text_to_video",
            },
            "target_operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "description": "Operation to score when operation='rank'.",
                "default": "text_to_video",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "9:16", "1:1"],
                "default": "16:9",
                "description": "Video aspect ratio. Passed through to the selected provider.",
            },
            "duration": {
                "type": "string",
                "description": "Duration hint (e.g., '5', '10'). Passed through to the selected provider.",
            },
            "reference_image_path": {
                "type": "string",
                "description": "Local path to a reference image for image_to_video. Auto-uploaded if the provider requires a URL.",
            },
            "reference_image_url": {
                "type": "string",
                "description": "URL of a reference image for image_to_video.",
            },
            "model": {
                "type": "string",
                "description": "Optional Veo model variant.",
            },
            "output_path": {"type": "string"},
            "profile": {
                "type": "string",
                "enum": ["openmontage_media"],
                "description": "Use the narrowed OpenMontage surface: Google Veo only.",
            },
        },
    }

    def _providers(self) -> list[BaseTool]:
        """Return only the provider in the active OpenMontage product."""
        from openmontage.tools.tool_registry import registry
        registry.ensure_discovered()
        tool = registry.get("veo_video")
        return [tool] if tool is not None else []

    def _providers_for_inputs(self, inputs: dict[str, object]) -> list[BaseTool]:
        return self._providers()

    @property
    def fallback_tools(self) -> list[str]:
        """Static fallback list for the active video provider."""
        return [t.name for t in self._providers()]

    def fallback_tools_for(self, inputs: dict[str, object]) -> list[str]:
        """Input-aware fallback list for the active video provider."""
        return [t.name for t in self._providers_for_inputs(inputs)]

    @property
    def provider_matrix(self) -> dict[str, dict[str, str]]:
        """Built at runtime from each provider's best_for field."""
        matrix = {}
        for tool in self._providers():
            strength = ", ".join(tool.best_for) if tool.best_for else tool.name
            matrix[tool.provider] = {"tool": tool.name, "strength": strength}
        return matrix

    def get_status(self) -> ToolStatus:
        if any(tool.get_status() == ToolStatus.AVAILABLE for tool in self._providers()):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, object]) -> float:
        candidates = self._filter_candidates(inputs, self._providers_for_inputs(inputs))
        if not candidates:
            return 0.0
        tool, _ = self._select_best_tool(inputs, candidates, self._prepare_task_context(inputs))
        return tool.estimate_cost(inputs) if tool else 0.0

    def estimate_runtime(self, inputs: dict[str, object]) -> float:
        candidates = self._providers_for_inputs(inputs)
        if not candidates:
            return 0.0
        tool, _ = self._select_best_tool(inputs, candidates, self._prepare_task_context(inputs))
        return tool.estimate_runtime(inputs) if tool else 0.0

    def execute(self, inputs: dict[str, object]) -> ToolResult:
        from openmontage.lib.scoring import rank_providers

        candidates = self._providers()

        # Rank mode — return scored provider rankings without generating
        if inputs.get("operation") == "rank":
            rank_inputs = self._rank_inputs(inputs)
            task_context = self._prepare_task_context(rank_inputs)
            candidates = self._filter_candidates(rank_inputs, candidates)
            rankings = rank_providers(candidates, task_context)
            return ToolResult(
                success=True,
                data={
                    "rankings": self._serialize_rankings(candidates, rankings),
                    "explanation": "\n".join(r.explain() for r in rankings[:5]),
                    "normalized_task_context": task_context,
                },
            )

        if inputs.get("operation", "text_to_video") not in {"text_to_video", "image_to_video"}:
            return ToolResult(
                success=False,
                error="OpenMontage video_selector supports only text_to_video and image_to_video.",
            )

        # Normal generation — use scored selection
        task_context = self._prepare_task_context(inputs)
        tool, score = self._select_best_tool(inputs, candidates, task_context)
        if tool is None:
            return ToolResult(success=False, error="No video generation provider available.")

        # Adapt input keys: stock tools use 'query' while generators use 'prompt'
        adapted = dict(inputs)
        if hasattr(tool, 'input_schema'):
            required = tool.input_schema.get("properties", {})
            if "query" in required and "query" not in adapted:
                adapted["query"] = adapted.get("prompt", "")

        # Auto-resolve reference_image_path to a URL for providers that need it
        if adapted.get("operation") == "image_to_video" and adapted.get("reference_image_path"):
            tool_props = getattr(tool, "input_schema", {}).get("properties", {})
            # If the provider uses image_url (not reference_image_path), upload and convert
            if "image_url" in tool_props and "image_url" not in adapted:
                try:
                    from openmontage.tools.video._shared import upload_image_fal
                    adapted["image_url"] = upload_image_fal(adapted["reference_image_path"])
                except Exception as e:
                    return ToolResult(success=False, error=f"Failed to upload reference image: {e}")

        result = tool.execute(adapted)
        if result.success:
            result.data.setdefault("selected_tool", tool.name)
            result.data["selected_provider"] = tool.provider
            result.data["selection_reason"] = score.explain() if score else f"Selected {tool.provider} ({tool.name})"
            if score:
                result.data["provider_score"] = score.to_dict()
            result.data.update(self._tool_context_payload(tool))
            result.data["alternatives_considered"] = [
                t.name for t in candidates
                if t.name != tool.name and t.get_status().value == "available"
            ]
            # Input-aware fallback list (drops image_selector for motion-required briefs).
            result.data.setdefault("fallback_tools", self.fallback_tools_for(inputs))
        return result

    def _select_best_tool(
        self,
        inputs: dict[str, object],
        candidates: list[BaseTool],
        task_context: dict[str, object],
    ) -> tuple[BaseTool | None, object]:
        """Select the best provider using scored ranking.

        Respects preferred_provider as a tie-breaker, but the scoring engine
        drives the primary selection.
        """
        from openmontage.lib.scoring import rank_providers, ProviderScore

        preferred = inputs.get("preferred_provider", "auto")
        allowed = set(inputs.get("allowed_providers") or [])
        if allowed:
            candidates = [tool for tool in candidates if tool.provider in allowed]
        candidates = self._filter_candidates(inputs, candidates)

        rankings = rank_providers(candidates, task_context)

        # Selectable tools, keyed by NAME (not provider). Keying by provider
        # string shadowed one of two tools that legitimately share a provider —
        # e.g. seedance_video (fal) and seedance_replicate both have
        # provider="seedance", so only the first-registered was ever reachable.
        # Keying by name keeps every backend selectable; ranking picks the best.
        selectable_by_name: dict[str, BaseTool] = {
            tool.name: tool for tool in candidates if self._tool_selectable(tool, inputs)
        }

        def _tool_for(score: object) -> BaseTool | None:
            return selectable_by_name.get(getattr(score, "tool_name", None))

        # If a preferred provider is explicitly requested, honor it ONLY when its
        # best ranked tool is within a configurable score gap of the overall top.
        # The prior code returned the preferred provider on the first ranking
        # match regardless of how far below the top it scored (the comment
        # claimed "unless drastically worse" but no gate enforced it).
        if preferred != "auto" and rankings:
            try:
                gap = float(inputs.get("preferred_provider_gap", self.PREFERRED_PROVIDER_GAP))
            except (TypeError, ValueError):
                gap = self.PREFERRED_PROVIDER_GAP
            top_score = rankings[0].weighted_score
            preferred_score = next(
                (s for s in rankings if s.provider == preferred and _tool_for(s) is not None),
                None,
            )
            if preferred_score is not None and preferred_score.weighted_score >= top_score - gap:
                return _tool_for(preferred_score), preferred_score

        # Return the highest-scored selectable provider
        for score in rankings:
            tool = _tool_for(score)
            if tool is not None:
                return tool, score

        return None, None

    def _prepare_task_context(self, inputs: dict[str, object]) -> dict[str, object]:
        from openmontage.lib.scoring import normalize_task_context

        return normalize_task_context(
            inputs.get("task_context", {}),
            prompt=str(inputs.get("prompt", "")),
            capability=self.capability,
            operation=str(inputs.get("operation", "text_to_video")),
        )

    @staticmethod
    def _rank_inputs(inputs: dict[str, object]) -> dict[str, object]:
        rank_inputs = dict(inputs)
        rank_inputs["operation"] = inputs.get("target_operation", "text_to_video")
        return rank_inputs

    @staticmethod
    def _tool_context_payload(tool: BaseTool) -> dict[str, object]:
        info = tool.get_info()
        return {
            "selected_tool_agent_skills": info.get("agent_skills", []),
            "required_agent_skills": info.get("agent_skills", []),
            "selected_tool_usage_location": info.get("usage_location"),
            "selected_tool_best_for": info.get("best_for", []),
        }

    def _serialize_rankings(self, candidates: list[BaseTool], rankings: list[object]) -> list[dict[str, object]]:
        tool_by_name = {tool.name: tool for tool in candidates}
        serialized: list[dict[str, object]] = []
        for score in rankings:
            item = score.to_dict()
            tool = tool_by_name.get(score.tool_name)
            if tool:
                info = tool.get_info()
                item["agent_skills"] = info.get("agent_skills", [])
                item["usage_location"] = info.get("usage_location")
                item["best_for"] = info.get("best_for", [])
                item["supports"] = info.get("supports", {})
                item["status"] = str(tool.get_status())
            serialized.append(item)
        return serialized

    def _filter_candidates(
        self,
        inputs: dict[str, object],
        candidates: list[BaseTool],
    ) -> list[BaseTool]:
        exact_model = inputs.get("model")
        if exact_model:
            model_matches = [
                tool for tool in candidates
                if exact_model in getattr(tool, "input_schema", {}).get("properties", {}).get("model", {}).get("enum", [])
                or exact_model in tool.get_info().get("model_catalog", {})
            ]
            if model_matches:
                candidates = model_matches

        operation = inputs.get("operation", "text_to_video")
        if operation == "rank":
            operation = inputs.get("target_operation", "text_to_video")

        filtered: list[BaseTool] = []
        matched_operation = False
        for tool in candidates:
            supports = getattr(tool, "supports", {})
            props = getattr(tool, "input_schema", {}).get("properties", {})

            if operation == "image_to_video":
                if supports.get("image_to_video") or "image_url" in props or "reference_image_url" in props:
                    matched_operation = True
                    if self._operation_ready(tool, "image_to_video"):
                        filtered.append(tool)
                continue

            matched_operation = True
            if self._operation_ready(tool, str(operation)):
                filtered.append(tool)

        return filtered if matched_operation else candidates

    @staticmethod
    def _operation_ready(tool: BaseTool, operation: str) -> bool:
        checker = getattr(tool, "is_operation_available", None)
        if not callable(checker):
            return True
        return bool(checker(operation))

    def _tool_selectable(self, tool: BaseTool, inputs: dict[str, object]) -> bool:
        """The active provider must be configured before selection."""
        return tool.get_status() == ToolStatus.AVAILABLE
