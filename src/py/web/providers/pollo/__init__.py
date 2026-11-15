"""Pollo image, video and audio models for chat mode.

Chat's generate_image / generate_video tools normally run on OpenRouter
models; this package lets them run on Pollo's models too, through the payload
engine in web/providers/pollo_engine/. They're listed in the chat catalogues
as "pollo/<model key>" (e.g. "pollo/seedream", "pollo/seedance20fast") and
bill the signed-in user's Pollo account (their per-user Pollo key).

Images are generated synchronously, like OpenRouter's. Videos mirror
openrouter.submit_video / get_video / download_video, with job ids prefixed
"pollo:" so chat's background video poller knows which API to ask.

Pollo bills in credits, not dollars, so Pollo media records `credits` on
its media item rather than adding to the OpenRouter `cost`.

The package is a facade over its modules:

- ``catalogue``: which models exist (chat catalogues, voices, model-key lookup)
- ``uploads``: local files to public URLs, which is all Pollo accepts
- ``tasks``: submitting a built generation, polling the task, fetching results
- ``submit``: starting image, video and audio jobs
- ``cost``: credit estimates
"""

from web.providers.pollo.catalogue import is_configured, is_pollo, is_pollo_job, list_models, list_voices
from web.providers.pollo.cost import estimate_cost
from web.providers.pollo.submit import generate_image, submit_audio, submit_video
from web.providers.pollo.tasks import download_video, get_video
from web.providers.pollo_errors import PolloError

NAME: str = "pollo"

__all__ = [
    "NAME",
    "PolloError",
    "download_video",
    "estimate_cost",
    "generate_image",
    "get_video",
    "is_configured",
    "is_pollo",
    "is_pollo_job",
    "list_models",
    "list_voices",
    "submit_audio",
    "submit_video",
]
