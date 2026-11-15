"""Importing chats from a ChatGPT data export (Settings → Data controls → Export data), to carry them on here.

The same upload and import also take this app's own chat export (see
web/transfer/export.py), told apart by what's in the zip.

The export's zip goes in <data>/imports/: copied there, or uploaded from
the browser in chunks (it's often gigabytes; nginx takes 25 MB a request).
Inside it:
    conversations.json    every chat: a tree of messages ("mapping") and the
                          one shown ("current_node"). Only the shown branch is
                          exported, and the image tool's messages are left out.
    library_files.json    every file: its chat ("origination_thread_id"), when
                          it was made and its type. Generated images are only
                          linked to their chat here, not to a message.
    file_<id>.dat         the files themselves (older exports: file-<id>-name.ext)

Each ChatGPT turn (a prompt and the replies to it) becomes a prompt and one
reply here. Uploaded images are on their prompt; generated ones go on the
reply to the latest prompt sent before they were made.

New chats go in the "ChatGPT" space (made on the first import), seeded with
the defaults of any chat started there; they can be moved out like any
other. Importing again (a newer export) only adds what's new: chats, messages
and images remember their ids there, chats unchanged since are skipped, and
chats the user deleted here stay deleted. A chat carried on in ChatGPT gets
the new turns; if it was carried on here too, they're a separate branch.

The modules:

- ``parse``: the export zip and its conversation trees, as prompt-and-reply turns
- ``media``: writing the export's images and videos into a chat's folder
- ``importer``: merging the turns into chats, and the run itself
- ``routes``: the folder listing, starting a run, and chunked uploads
"""

from web.transfer.chatgpt.common import MISSING
from web.transfer.chatgpt.importer import run_import
from web.transfer.chatgpt.routes import reset_jobs, router

__all__ = ["MISSING", "reset_jobs", "router", "run_import"]
