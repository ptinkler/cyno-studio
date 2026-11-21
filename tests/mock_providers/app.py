"""The mock providers' web app."""

from fastapi import FastAPI

from tests.mock_providers import control, venice

app = FastAPI(title="Mock AI providers")
app.include_router(control.router)
app.include_router(venice.router)
