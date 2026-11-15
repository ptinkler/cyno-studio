"""The Turn: one chat turn run in a worker thread.

Streams the chat model, runs its generate_image/generate_video/create_* tools via the generation module,
persists everything, and starts video pollers for async jobs. The work is layered over several modules
(`turn_base` -> `turn_history` -> `turn_generation` -> `turn_tools`); this one adds the entry point, the
explicit image/video/audio modes and the title.
"""

import contextlib
import logging
import os
import re
import threading
from typing import TypedDict

from web.chat import generation
from web.chat.catalogue import ModelInfo, model_info
from web.chat.constants import (
    DEFAULT_TITLE,
    TITLE_WAIT_SECONDS,
)
from web.chat.errors import (
    PromptRequiredError,
    ToolImageRequiredError,
    VideoInputRequiredError,
)
from web.chat.generation import RefLimits, plan_refs
from web.chat.helpers import message_out
from web.chat.turn_generation import ImageSpec, VideoSpec
from web.chat.turn_tools import ToolsTurn
from web.chat.workers import ctx_thread
from web.core.metadata.models import ChatMessage
from web.providers import openrouter, provider_for

log = logging.getLogger(__name__)

_MAX_TITLE_CHARS = 60  # a title made from the prompt is cut to this, ending in an ellipsis


class _TitleJob(TypedDict):
    prompt: str
    title: str | None
    cost: float
    thread: threading.Thread | None


class Turn(ToolsTurn):
    """Runs one assistant turn and persists it. `emit` receives UI events."""

    def run(self) -> None:
        """Run this turn, persist its final state, and emit the completion event."""
        title_job = self._start_title()
        try:
            self._run_mode()
            status, error = ("done", None)
        except openrouter.OpenRouterError as e:
            status, error = "error", str(e)
        except Exception as e:  # never leave a message stuck in "streaming"
            log.exception("turn for message %s failed", self.message_id)
            status, error = "error", f"{type(e).__name__}: {e}"
        if self.cancel.is_set() and status == "done":
            self.content = self.content.rstrip() + ("\n\n" if self.content else "") + "*(stopped)*"
        self._finish_title(title_job)
        msg = self.db.update_chat_message(
            self.message_id,
            content=self.content,
            status=status,
            error=error,
            cost=round(self.cost, 6) if self.cost else None,
        )
        if error:
            self.emit({"type": "error", "message": error})
        self.emit({"type": "done", "message": message_out(msg) if msg else None})

    def _run_mode(self) -> None:
        """Do the turn's work in the composer's mode (explicit media, or chat with tools)."""
        if self.s.mode == "image":
            self._direct_image()
        elif self.s.mode == "video":
            self._direct_video()
        elif self.s.mode == "audio":
            self._direct_audio()
        else:
            self._chat(tools_enabled=self.s.mode == "auto")

    def _direct_image(self) -> None:
        user = self._last_user()
        prompt = (user.content if user else "").strip()
        info = model_info("image", self.s.image_model) or {}
        if info.get("tool"):
            return self._direct_image_tool(user, prompt, info)
        if not prompt:
            raise PromptRequiredError("image")
        chars = self.characters  # every attached character
        dropped: list[str] = []
        refs = [
            file
            for media in (user.media if user else [])
            if media.get("kind") == "image" and isinstance((file := media.get("file")), str)
        ]
        if self._accepts_refs():
            limits = RefLimits(
                self.s.image_limit, after=len(refs), max_refs=self._max_refs(), choices=self.s.ref_choices
            )
            refs, dropped = plan_refs(refs + self._pinned_images(), chars, limits)
        self._generate_image(ImageSpec(prompt, self.s.image_options.aspect_ratio, refs, chars=chars, dropped=dropped))
        return None

    def _direct_image_tool(self, user: ChatMessage | None, prompt: str, info: ModelInfo) -> None:
        """An image tool (upscale, background remover…): the attached image is the whole input.

        The model's name stands in for the prompt, so the
        card can be retried.
        """
        files = [
            file
            for media in (user.media if user else [])
            if media.get("kind") == "image" and isinstance((file := media.get("file")), str)
        ]
        if not files:
            raise ToolImageRequiredError
        self._generate_image(ImageSpec(prompt or info.get("name") or "Image tool", None, files[:1]))

    def _direct_video(self) -> None:
        user = self._last_user()
        prompt = (user.content if user else "").strip()
        frames = [
            file
            for media in (user.media if user else [])
            if media.get("kind") == "image" and isinstance((file := media.get("file")), str)
        ]
        info = model_info("video", self.s.video_model) or {}
        if not prompt and info.get("no_prompt"):
            prompt = info.get("name") or "Video tool"  # the source file is the whole input
        # Reference-to-video: a prompt that mentions refs as [@name], or any
        # attached video/audio, routes to the model's refs branch with a named
        # list of all attachments. A lone image with no mention stays plain
        # image-to-video.
        ref_mode = info.get("ref_mode")
        has_av = any(m.get("file") and m["kind"] in ("video", "audio") for m in (user.media if user else []))
        ref_items = self.build_ref_items(ref_mode) if ref_mode and ("[@" in prompt or has_av) else None
        if not prompt and not frames and not ref_items:
            raise VideoInputRequiredError
        # Attached images: the first frame, the last frame (first+last-frame
        # models) and, for reference models, all of them are references
        spec = VideoSpec(
            prompt,
            self.s.video_options.duration,
            self.s.video_options.aspect_ratio,
            frames[0] if frames else None,
            chars=self.characters,
            last_frame=frames[1] if len(frames) > 1 else None,
            attached=frames,
            ref_items=ref_items,
        )
        self._generate_video(spec)

    def _direct_audio(self) -> None:
        user = self._last_user()
        prompt = (user.content if user else "").strip()
        if not prompt:
            raise PromptRequiredError("audio")
        self._generate_audio(prompt)

    def _start_title(self) -> _TitleJob | None:
        """On a new chat's first turn, ask a text model for a short title while the reply is made.

        Uses CHAT_TITLE_MODEL, else the chat model.
        """
        conv = self.db.get_conversation(self.conv_id)
        if not conv or conv.title != DEFAULT_TITLE:
            return None
        first = next((m for m in self.history if m.role == "user" and m.content), None)
        if not first:
            return None
        job: _TitleJob = {"prompt": first.content, "title": None, "cost": 0.0, "thread": None}
        # The user's title model (Settings), else CHAT_TITLE_MODEL, else the chat model
        chosen = self.db.get_settings().title_model or os.environ.get("CHAT_TITLE_MODEL")
        model = chosen or self.s.text_model
        # Direct image/video/audio sends involve no text model, so without a chosen
        # title model the prompt itself (tidied) titles the chat
        direct = self.s.mode in ("image", "video", "audio") and not chosen
        if model and not direct and provider_for(model).is_configured():

            def work() -> None:
                # No title from the model: the prompt stands in
                with contextlib.suppress(Exception):
                    job["title"], job["cost"] = generation.generate_title(model, first.content)

            job["thread"] = ctx_thread(work, name=f"chat-title-{self.message_id}")
            job["thread"].start()
        return job

    def _finish_title(self, job: _TitleJob | None) -> None:
        """Title the chat: the model's title if it came back in time, else the start of the first prompt.

        Its cost goes on this reply.
        """
        if not job:
            return
        title = None
        if job["thread"]:
            job["thread"].join(timeout=TITLE_WAIT_SECONDS)
            if not job["thread"].is_alive():
                title = job["title"]
                self.cost += job["cost"] or 0
        if not title:
            # [@video1] reference tags read as plain words in a title
            title = " ".join(re.sub(r"\[@([^\]]+)\]", r"\1", job["prompt"]).split())
            if len(title) > _MAX_TITLE_CHARS:
                title = title[: _MAX_TITLE_CHARS - 3].rsplit(" ", 1)[0] + "…"
        conv = self.db.get_conversation(self.conv_id)
        if not conv or conv.title != DEFAULT_TITLE:  # renamed meanwhile
            return
        self.db.update_conversation(self.conv_id, title=title)
        self.emit({"type": "title", "title": title})
