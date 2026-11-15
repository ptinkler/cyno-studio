"""The chat API router, shared by the route modules and the engine so every.

chat endpoint hangs off one APIRouter with the sign-in dependency.
"""

import threading

from fastapi import APIRouter, Depends

from web.users import require_user

router = APIRouter(prefix="/api/chat", dependencies=[Depends(require_user)])

# Starting a turn checks that the chat is idle and then marks a reply as
# streaming; a media retry checks its card isn't already running and then
# marks it pending. Each is a check-then-act, and FastAPI runs these routes on
# a thread pool — so a double click (or two tabs) could slip both requests
# past the check and pay twice. One lock makes each check-and-mark atomic.
start_lock = threading.Lock()
