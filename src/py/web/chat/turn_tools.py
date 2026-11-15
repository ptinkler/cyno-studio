"""The chat model's tool loop: streaming a round, running its generate_* / create_* calls."""

import json
import logging
from collections.abc import Mapping
from typing import TypedDict, cast

from web import characters
from web.chat.catalogue import auto_ratio, model_info
from web.chat.constants import (
    CHAT_ROUND_SECONDS,
    MAX_TOOL_ROUNDS,
)
from web.chat.errors import (
    ModelNotSelectedError,
)
from web.chat.generation import (
    is_moderation_error,
)
from web.chat.helpers import conversation_dir
from web.chat.tools import (
    AUDIO_TOOL_RESULT,
    IMAGE_TOOL_RESULT,
    TOOLS_AUDIO,
    TOOLS_CREATE_CHARACTER,
    TOOLS_CREATE_INSTRUCTION,
    TOOLS_IMAGE,
    TOOLS_VIDEO,
    VIDEO_TOOL_RESULT,
    with_character_arg,
)
from web.chat.turn_generation import GenerationTurn
from web.core.metadata.models import Character
from web.jsonutil import loads
from web.providers import openrouter, stream_chat
from web.types import ChatChunk, JsonValue, ToolCallDelta

log = logging.getLogger(__name__)

_FIRST_LAST_FRAMES = 2  # first+last-frame models take the two most recent images


class _ToolFunction(TypedDict):
    name: str
    arguments: str


class _ToolCall(TypedDict):
    id: str
    type: str
    function: _ToolFunction


class ToolsTurn(GenerationTurn):
    """The chat model's tool loop: streaming a round, running its generate_* / create_* calls."""

    def _chat(self, *, tools_enabled: bool) -> None:
        if not self.s.text_model:
            raise ModelNotSelectedError("text")
        model = self.s.text_model
        info = model_info("text", model)
        use_tools = tools_enabled and (info is None or info.get("supports_tools"))
        vision = info is None or "image" in (info.get("input_modalities") or [])
        messages = self._build_llm_messages(vision=vision, as_tool_calls=bool(use_tools and self._tools()))

        offer_tools = True
        for round_no in range(MAX_TOOL_ROUNDS):
            # Last round: withhold tools so the loop can't run forever. Rebuilt
            # each round: a character created mid-turn joins the name lists.
            tools = self._tools() if use_tools else []
            round_tools = (tools or None) if offer_tools and round_no < MAX_TOOL_ROUNDS - 1 else None
            text, tool_calls = self._stream_round(model, messages, round_tools)
            if self.cancel.is_set() or not tool_calls:
                return
            messages.append(
                cast("dict[str, JsonValue]", {"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            )
            results = self._run_tool_calls(tool_calls, messages)
            if results is None:
                return
            offer = self._offer_tools_next(offer_tools=offer_tools, text=text, tool_calls=tool_calls, results=results)
            if offer is None:
                return
            offer_tools = offer

    def _run_tool_calls(
        self, tool_calls: list[_ToolCall], messages: list[dict[str, JsonValue]]
    ) -> list[dict[str, JsonValue]] | None:
        """Run each tool call, adding its result to `messages`; None if the turn was cancelled."""
        results: list[dict[str, JsonValue]] = []
        for call in tool_calls:
            result = self._run_tool(call)
            results.append(result)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
            if self.cancel.is_set():
                return None
        return results

    @staticmethod
    def _offer_tools_next(
        *, offer_tools: bool, text: str, tool_calls: list[_ToolCall], results: list[dict[str, JsonValue]]
    ) -> bool | None:
        """Whether the next round still offers tools; None when the turn is over."""
        # A moderation block ends the turn: the user chooses Retry or
        # another model on the failed card (no automatic re-attempt)
        if any(r.get("moderated") for r in results):
            return None
        # Saving a character or an instruction makes nothing to show — carry on
        no_media = ("create_character", "create_instruction")
        made_media = any(c["function"]["name"] not in no_media for c in tool_calls)
        if made_media and all(r.get("ok") for r in results):
            # The media was made. If the model also wrote its reply, the
            # reply is complete — asking it to continue just makes it
            # start over (duplicate story + duplicate image). If it called
            # the tool before writing anything, let it write, without tools.
            return None if text.strip() else False
        # (After a non-moderation failure the model keeps its tools and
        # can explain or try again.)
        return offer_tools

    def _tools(self) -> list[dict[str, JsonValue]]:
        names = list(dict.fromkeys(c.name for c in self.characters))  # a name shared by two is listed once
        tools: list[dict[str, JsonValue]] = (
            [cast("dict[str, JsonValue]", TOOLS_CREATE_CHARACTER)] if self.s.image_model else []
        )
        if self.s.image_model:
            tools.insert(0, with_character_arg(TOOLS_IMAGE, names))
        if self.s.video_model:
            tools.append(with_character_arg(TOOLS_VIDEO, names))
        if self.s.audio_model:
            tools.append(cast("dict[str, JsonValue]", TOOLS_AUDIO))
        # Needs no media model: applies to the chat model itself.
        tools.append(cast("dict[str, JsonValue]", TOOLS_CREATE_INSTRUCTION))
        return tools

    def _add_chunk_cost(self, chunk: ChatChunk) -> None:
        """Add the cost a chunk reports (providers send it with the usage)."""
        usage = chunk.get("usage")
        chunk_cost = usage.get("cost") if usage else None
        if isinstance(chunk_cost, int | float | str) and not isinstance(chunk_cost, bool):
            self.cost += float(chunk_cost)

    @staticmethod
    def _merge_tool_call_deltas(calls: dict[int, _ToolCall], deltas: list[ToolCallDelta]) -> None:
        """Fold streamed tool-call fragments into the calls built so far (by slot index)."""
        for tc in deltas:
            slot = calls.setdefault(
                tc.get("index", 0),
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            call_id = tc.get("id")
            if isinstance(call_id, str):
                slot["id"] = call_id
            fn = tc.get("function") or {}
            fn_name, arguments = fn.get("name"), fn.get("arguments")
            slot["function"]["name"] += fn_name if isinstance(fn_name, str) else ""
            slot["function"]["arguments"] += arguments if isinstance(arguments, str) else ""

    def _stream_round(
        self, model: str, messages: list[dict[str, JsonValue]], tools: list[dict[str, JsonValue]] | None
    ) -> tuple[str, list[_ToolCall]]:
        """One chat completion, streamed to the UI."""
        text = ""
        calls: dict[int, _ToolCall] = {}
        finish = None
        if self.content and not self.content.endswith("\n\n"):
            self._append("\n\n")
        for chunk in stream_chat(
            model,
            messages,
            tools,
            session_id=self.conv_id,
            max_seconds=CHAT_ROUND_SECONDS,
            should_stop=self.cancel.is_set,
        ):
            if self.cancel.is_set():
                break
            self._add_chunk_cost(chunk)
            for choice in chunk.get("choices") or []:
                finish = choice.get("finish_reason") or finish
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    text += content
                    self._append(content)
                self._merge_tool_call_deltas(calls, delta.get("tool_calls") or [])
        tool_calls = [c for _, c in sorted(calls.items()) if c["function"]["name"]]
        for i, c in enumerate(tool_calls):
            c["id"] = c["id"] or f"call_{i}"
        # Diagnostics: distinguishes "model never called the tool" from
        # "we failed to parse the call" when media goes missing
        log.info(
            "msg %s %s: finish=%s tools_offered=%s tool_calls=%s raw_call_slots=%d text_chars=%d",
            self.message_id,
            self.s.text_model,
            finish,
            bool(tools),
            [c["function"]["name"] for c in tool_calls],
            len(calls),
            len(text),
        )
        return text, tool_calls

    def _run_tool(self, call: _ToolCall) -> dict[str, JsonValue]:
        name = call["function"]["name"]
        args, error = self._parse_tool_arguments(call["function"]["arguments"])
        if args is None:
            return {"ok": False, "error": error or "Arguments were not valid JSON"}
        if name == "create_character":
            return self._create_character(args)
        if name == "create_instruction":
            return self._create_instruction(args)
        if name not in ("generate_image", "generate_video", "generate_audio"):
            return {"ok": False, "error": f"Unknown tool {name}"}
        # Models sometimes repeat a call word for word (twice in one response,
        # or again next round). Each would be billed, so a call identical to
        # one that already went through is answered without running it again.
        # A failed call isn't remembered, so the model can still retry it.
        fingerprint = f"{name}:{json.dumps(args, sort_keys=True)}"
        if fingerprint in self._calls_made:
            log.warning("msg %s: skipped a repeated %s call", self.message_id, name)
            return {"ok": True, "note": "Already made exactly this earlier in this reply — not made again."}
        result = self._audio_tool(args) if name == "generate_audio" else self._media_tool(name, args)
        if result.get("ok"):
            self._calls_made.add(fingerprint)
        return result

    def _media_tool(self, name: str, args: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt is required"}
        source = self._latest_image() if args.get("source_image") == "latest" else None
        if args.get("source_image") == "latest" and not source:
            return {"ok": False, "error": "There is no earlier image in the conversation to use"}
        raw_names = args.get("characters")
        names = [name for name in raw_names if isinstance(name, str)] if isinstance(raw_names, list) else []
        chars = self._pick_characters(names, prompt)
        try:
            if name == "generate_image":
                return self._image_tool(prompt, args, source, chars)
            return self._video_tool(prompt, args, source, chars)
        except openrouter.OpenRouterError as e:
            return {"ok": False, "error": str(e), "moderated": is_moderation_error(e)}

    @staticmethod
    def _parse_tool_arguments(arguments: str) -> tuple[Mapping[str, JsonValue] | None, str | None]:
        try:
            parsed = loads(arguments or "{}")
        except json.JSONDecodeError:
            return None, "Arguments were not valid JSON"
        if not isinstance(parsed, dict):
            return None, "Arguments must be a JSON object"
        return cast("Mapping[str, JsonValue]", parsed), None

    def _audio_tool(self, args: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt is required"}
        try:
            self._generate_audio(prompt)
        except openrouter.OpenRouterError as e:
            return {"ok": False, "error": str(e), "moderated": is_moderation_error(e)}
        return {"ok": True, "result": AUDIO_TOOL_RESULT}

    def _image_tool(
        self, prompt: str, args: Mapping[str, JsonValue], source: str | None, chars: list[Character]
    ) -> dict[str, JsonValue]:
        # Aspect ratio is the composer's to set, not the chat model's. A ratio
        # picked there wins; left on "auto" it becomes the image model's own
        # "auto" value if it has one, else nothing — the model's natural shape.
        ratio = self.s.image_options.aspect_ratio or auto_ratio("image", self.s.image_model)
        refs, dropped = self._image_refs(args, source, chars)
        ref_args = {k: args[k] for k in ("source_image", "keep_consistent", "characters") if k in args}
        self._generate_image(prompt, ratio, refs, ref_args, chars, dropped)
        result: dict[str, JsonValue] = {"ok": True, "result": IMAGE_TOOL_RESULT}
        if chars:
            result["characters"] = [c.name for c in chars]
        pinned = self._pinned_images()
        if refs:
            result["reference_images"] = len(refs)
            if dropped:
                result["references_left_out"] = f"{len(dropped)} (the image model takes at most {len(refs)})"
            if set(refs) & set(pinned):
                result["pinned_by_user"] = len(set(refs) & set(pinned))
        elif (ref_args or pinned) and not self._accepts_refs():
            result["note"] = "The selected image model can't take reference images, so none were sent."
        return result

    def _video_tool(
        self, prompt: str, args: Mapping[str, JsonValue], source: str | None, chars: list[Character]
    ) -> dict[str, JsonValue]:
        # The composer's settings beat the model's guesses; an animated image's own shape does too
        opts = self.s.video_options
        ratio_arg = args.get("aspect_ratio")
        ratio = opts.aspect_ratio or (ratio_arg if isinstance(ratio_arg, str) and not source else None)
        duration_arg = args.get("duration")
        duration = opts.duration or (
            duration_arg if isinstance(duration_arg, int) and not isinstance(duration_arg, bool) else None
        )
        last = None
        if "last_frame" in ((model_info("video", self.s.video_model) or {}).get("frame_images") or []):
            # First+last-frame models: the two most recent images, older one first
            recent = self._latest_images(_FIRST_LAST_FRAMES)
            if len(recent) == _FIRST_LAST_FRAMES:
                source, last = recent[1], recent[0]
        self._generate_video(prompt, duration, ratio, source, chars, last_frame=last)
        return {"ok": True, "result": VIDEO_TOOL_RESULT}

    def _create_character(self, args: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        name = str(args.get("name") or "").strip()[:100]
        if not name:
            return {"ok": False, "error": "name is required"}
        # Names needn't be unique: only one already in this chat stops it (the
        # model should use that one). A library character of the same name
        # that isn't attached is someone else — this chat gets its own.
        existing = next((c for c in self.characters if c.name.strip().lower() == name.lower()), None)
        if existing:
            return {
                "ok": False,
                "error": f"{name} is already one of this chat's characters; name them in `characters` to use them",
            }
        images = args.get("images")
        try:
            n = max(1, min(4, int(images or 1))) if isinstance(images, str | int | float) else 1
        except (TypeError, ValueError):
            n = 1
        files = [p for p in (conversation_dir(self.conv_id) / f for f in self._latest_images(n)) if p.is_file()]
        if not files:
            return {"ok": False, "error": "There is no image in the conversation to make the character from"}
        char = characters.create_from_files(
            name, str(args.get("description") or "").strip()[:4000], files, self.conv_id, self.db
        )
        self._attach([char])
        return {
            "ok": True,
            "result": f"Character {name} saved with {len(files)} reference image(s) and attached "
            f"to this chat. Name them in generate_image's `characters` to use them.",
        }

    def _create_instruction(self, args: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        """Save an instruction snippet and attach it to this chat.

        Keep existing snippets and groups; the new instruction takes effect
        on the next reply because this turn's system prompt is already built.
        """
        name = str(args.get("name") or "").strip()[:255]
        content = str(args.get("content") or "").strip()[:20000]
        if not name:
            return {"ok": False, "error": "name is required"}
        if not content:
            return {"ok": False, "error": "content is required"}
        # Only an instruction already applied to this chat stops it; the same
        # name elsewhere in the library is a separate instruction.
        if any(i.name.strip().lower() == name.lower() for i in self._chat_instructions()):
            return {"ok": False, "error": f"This chat already has an instruction called {name}; pick another name."}
        item = self.db.save_instruction(name=name, content=content)
        conv = self.db.get_conversation(self.conv_id)
        ids = [*(conv.instruction_ids if conv else []), item.id]
        self.db.update_conversation(self.conv_id, instruction_ids=ids)
        self.emit({"type": "instructions", "instruction_ids": ids, "instruction": item.to_dict()})
        return {
            "ok": True,
            "result": f"Instruction “{name}” saved and attached to this chat; it applies from your next reply. "
            f"The user can edit it, group it, or attach it to other chats from the Instructions panel.",
        }
