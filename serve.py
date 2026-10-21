"""Dev entry point: no reloader, no surprises.

Set HIKARIN_PORT to override (default 8411).

`uvicorn --reload` keeps a module cache that can serve stale routes after
edits to files it decides are unrelated. For a single-process local tool the
reloader earns nothing and costs a class of "my change did not apply" bugs, so
run it plain and restart when you change backend code.
"""

import os

import uvicorn

PORT = int(os.environ.get("HIKARIN_PORT", "8411"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, reload=False)
