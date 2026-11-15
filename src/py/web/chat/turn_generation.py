"""Generating an image, video or audio clip for a turn and recording it on its media card."""

import logging
from collections.abc import Mapping, Sequence

from web.chat import polling
from web.chat.audio import audio_params, submit_audio_generation
from web.chat.catalogue import fit_video_params, model_info
from web.chat.errors import (
    ModelNotSelectedError,
)
from web.chat.generation import (
    ImageResult,
    dedupe,
    exchange_fields,
    failure_fields,
    image_context,
    is_conversational,
    plan_refs,
    run_image_generation,
    submit_video_generation,
    take_log,
)
from web.chat.helpers import new_media, saved_media
from web.chat.turn_history import HistoryTurn
from web.core.metadata.models import Character
from web.providers import openrouter
from web.types import JsonValue

log = logging.getLogger(__name__)


class GenerationTurn(HistoryTurn):
    """Generating an image, video or audio clip for a turn and recording it on its media card."""

    def _image_params(
        self,
        aspect_ratio: str | None,
        ref_files: list[str],
        ref_args: dict[str, JsonValue] | None,
        chars: list[Character] | None,
        dropped: list[str] | None,
    ) -> dict[str, JsonValue]:
        """The settings stored on an image card so a failed image can be retried as-is."""
        params: dict[str, JsonValue] = {
            "aspect_ratio": aspect_ratio,
            "resolution": self.s.image_options.resolution,
            "refs": ref_files,
        }
        if dropped:
            params["refs_dropped"] = dropped  # more than the image model takes
        if ref_args:
            params["ref_args"] = ref_args  # the model's own reference choices, replayed in history
        if chars:
            params["characters"] = [c.id for c in chars]  # described in the prompt at generation time
            params["character_names"] = [c.name for c in chars]  # for display
        return params

    def _conversation_for_image(
        self, prompt: str, ref_files: list[str], chars: list[Character] | None, params: dict[str, JsonValue]
    ) -> list[dict[str, JsonValue]]:
        """The conversation sent to a conversational image model, like the Gemini app.

        Also records on `params` that it was used, so a retry does the same.
        """
        direct = self.s.mode == "image"
        params.update(context=True, direct=direct, history_limit=self.s.history_limit, image_limit=self.s.image_limit)
        return image_context(
            self.conv_id,
            self.history,
            self.s.history_limit,
            self.content,
            None if direct else prompt,
            ref_files,
            self.instructions,
            chars,
            self.s.image_limit,
        )

    def _store_images(
        self, item: dict[str, JsonValue], params: dict[str, JsonValue], prompt: str, result: ImageResult
    ) -> None:
        """Put the first image on its card; any further images become cards of their own."""
        names, cost, credit_cost, sent = result
        sent, exchange = take_log(sent)
        self._update_media(
            item, status="done", file=names[0], cost=cost, credits=credit_cost, params={**params, **sent}, **exchange
        )
        for name in names[1:]:
            self._add_media(saved_media("image", "generated", name, prompt=prompt, model=self.s.image_model))

    def _generate_image(
        self,
        prompt: str,
        aspect_ratio: str | None,
        ref_files: list[str],
        ref_args: dict[str, JsonValue] | None = None,
        chars: list[Character] | None = None,
        dropped: list[str] | None = None,
    ) -> None:
        if not self.s.image_model:
            raise ModelNotSelectedError("image")
        params = self._image_params(aspect_ratio, ref_files, ref_args, chars, dropped)
        context = (
            self._conversation_for_image(prompt, ref_files, chars, params)
            if is_conversational(self.s.image_model)
            else None
        )
        item = new_media("image", "generated", prompt=prompt, model=self.s.image_model, params=params)
        self._add_media(item)
        try:
            result = run_image_generation(self.conv_id, self.s.image_model, prompt, params, context)
        except openrouter.OpenRouterError as e:
            self._update_media(item, **failure_fields(e))
            raise
        cost = result[1]
        if cost:
            self.cost += float(cost)
        self._store_images(item, params, prompt, result)

    def _generate_video(
        self,
        prompt: str,
        duration: int | None,
        aspect_ratio: str | None,
        first_frame: str | None,
        chars: list[Character] | None = None,
        last_frame: str | None = None,
        attached: list[str] | None = None,
        ref_items: Sequence[Mapping[str, JsonValue]] | None = None,
    ) -> None:
        if not self.s.video_model:
            raise ModelNotSelectedError("video")
        duration, aspect_ratio, resolution = fit_video_params(
            self.s.video_model, duration, aspect_ratio, self.s.video_options.resolution
        )
        # Reference-to-video supersedes the singular first frame: the attachments
        # all ride in the named refs list instead.
        if ref_items:
            first_frame = None
        params: dict[str, JsonValue] = {
            "duration": duration,
            # Remembered so reusing a generation's settings puts Length back on
            # Auto rather than pinning whatever Auto resolved to (never sent).
            "duration_auto": bool(self.s.video_options.duration_auto),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "first_frame": first_frame,
            "generate_audio": self.s.video_options.generate_audio,
        }
        if ref_items:
            params["ref_items"] = ref_items
        if chars:
            params["characters"] = [c.id for c in chars]
        params.update(self._video_inputs(first_frame, last_frame, attached or [], chars or []))
        item = new_media("video", "generated", prompt=prompt, model=self.s.video_model, params=params)
        self._add_media(item)
        try:
            job = submit_video_generation(self.conv_id, self.s.video_model, prompt, params)
        except openrouter.OpenRouterError as e:
            self._update_media(item, **failure_fields(e))
            raise
        # Pollo reports what it was actually sent, defaults included
        self._update_media(
            item, job_id=job["id"], params={**params, **job.get("params", {})}, **exchange_fields(job.get("log"))
        )
        polling.start_video_poller(self.conv_id, self.message_id, str(item["id"]), job["id"])

    def _video_inputs(
        self, first_frame: str | None, last_frame: str | None, attached: list[str], chars: list[Character]
    ) -> dict[str, JsonValue]:
        """The extra inputs the video model's family takes (Venice).

        These are reference images (attached ones, the frame, characters' images and pins), a last frame, or the
        chat's latest video.
        """
        info = model_info("video", self.s.video_model) or {}
        out: dict[str, JsonValue] = {}
        if info.get("reference_images") or info.get("family") == "motion":
            own = dedupe([*attached, *([first_frame] if first_frame else []), *self._pinned_images()])
            out["refs"], _ = plan_refs(
                own,
                chars,
                None,
                after=len(attached) or (1 if first_frame else 0),
                max_refs=info.get("max_refs"),
                choices=self.s.ref_choices,
            )
        if last_frame and "last_frame" in (info.get("frame_images") or []):
            out["last_frame"] = last_frame
        if info.get("video_input"):
            out["source_video"] = self._latest_video()
        if info.get("audio_input"):
            out["source_audio"] = self._latest_audio()
        return out

    def _generate_audio(self, prompt: str) -> None:
        if not self.s.audio_model:
            raise ModelNotSelectedError("audio")
        params = audio_params(self.s.audio_options)
        if (model_info("audio", self.s.audio_model) or {}).get("audio_input"):
            params["source_audio"] = self._latest_audio()  # the clip to clone the voice from
        item = new_media("audio", "generated", prompt=prompt, model=self.s.audio_model, params=params)
        self._add_media(item)
        try:
            job = submit_audio_generation(self.conv_id, self.s.audio_model, prompt, params)
        except openrouter.OpenRouterError as e:
            self._update_media(item, **failure_fields(e))
            raise
        self._update_media(
            item, job_id=job["id"], params={**params, **job.get("params", {})}, **exchange_fields(job.get("log"))
        )
        polling.start_video_poller(self.conv_id, self.message_id, str(item["id"]), job["id"])
