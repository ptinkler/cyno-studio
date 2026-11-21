"""A stand-in for the AI providers, for end-to-end tests: run it and point the app's provider base URLs at it.

Each mock model behaves one way on purpose (instant, slow, dropped connection, content filter, failed job...), so a
test picks a behaviour by picking a model. ``/__mock/requests`` returns what the app sent, so a test can check
exactly which images, prompts and options went out. See ``python -m tests.mock_providers --help``.
"""
