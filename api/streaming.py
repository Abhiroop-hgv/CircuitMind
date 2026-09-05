"""
Server-sent events for the long-running pipelines.

A run reports as it goes rather than answering at the end, so the interface can
show which stage is working. The work happens on a thread and frames arrive
through a queue, because the agents are synchronous and blocking the event loop
with them would stall every other request.
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Dict, Generator, Optional

from fastapi.responses import StreamingResponse

def sse(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _stream(work) -> StreamingResponse:
    """
    Run `work` on a thread, pushing progress onto a queue the response drains.

    The agents are synchronous and talk to Postgres; running them inside the
    event loop would block every other request for the length of the pipeline.
    """
    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def emit(event: str, **data):
        q.put(sse(event, data))

    def runner():
        try:
            work(emit)
        except Exception as exc:  # surfaced to the UI rather than swallowed
            q.put(sse("error", {"message": f"{type(exc).__name__}: {exc}"}))
        finally:
            q.put(None)

    threading.Thread(target=runner, daemon=True).start()

    def generate() -> Generator[str, None, None]:
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
