"""Venice (https://venice.ai) text, image and video models for chat mode.

Listed in the chat's catalogues as "venice/<model id>" and billed to the
signed-in user's Venice account (their per-user Venice key), alongside OpenRouter's and Pollo's models.

  • text   — POST /chat/completions (OpenAI-compatible, streamed; tools on
             models that support function calling)
  • image  — POST /image/generate, or /image/multi-edit when reference images
             are sent. Venice splits these into separate models
             ("seedream-v5-pro" / "seedream-v5-pro-edit"); one catalogue entry
             covers both and the right one is picked per request.
  • video  — POST /video/queue, then /video/retrieve until the MP4 comes back.
             Text-to-video and image-to-video are separate models too
             ("…-text-to-video…" / "…-image-to-video…"), paired the same way.

Safe mode is always off (Venice blurs adult content otherwise), and Venice's
own system prompt is never added to chats.

Video job ids are "venice:<model>:<queue_id>" — retrieve needs the model.

The package is a facade over its modules:

- ``client``: base URL, auth, error mapping, the shared connection, the balance
- ``models``: the per-user catalogue (fetched, paired, priced, cached)
- ``text``: streamed chat completions
- ``images``: image generation and edits
- ``jobs``: video jobs from queue to the finished MP4
"""

from web.core.key_caches import on_keys_changed
from web.providers.venice import client, jobs, models
from web.providers.venice.client import get_api_key, get_balances, is_configured
from web.providers.venice.images import generate_image
from web.providers.venice.jobs import download_video, get_video, is_venice_job, submit_video
from web.providers.venice.models import is_venice, list_models, model_info
from web.providers.venice.text import stream_chat

NAME: str = "venice"


@on_keys_changed
def clear_caches() -> None:
    """Clear catalogue, quote, balance, and job-state caches.

    Called when a user's keys change and by tests between cases.
    """
    models.clear()
    jobs.clear()
    client.clear()


__all__ = [
    "NAME",
    "clear_caches",
    "download_video",
    "generate_image",
    "get_api_key",
    "get_balances",
    "get_video",
    "is_configured",
    "is_venice",
    "is_venice_job",
    "list_models",
    "model_info",
    "stream_chat",
    "submit_video",
]
