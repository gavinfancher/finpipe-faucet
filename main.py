import logging
import os
import socket
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from rich.logging import RichHandler

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler()])

for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    log = logging.getLogger(name)
    log.handlers = [RichHandler(show_path=False)]
    log.propagate = False


def find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("localhost", preferred)) != 0:
            return preferred  # preferred port is free
    # fall back to OS-assigned free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    preferred = int(os.getenv("API_PORT", "8000"))
    port = find_free_port(preferred)
    if port != preferred:
        logging.getLogger(__name__).warning("port %d in use, using %d instead", preferred, port)
    uvicorn.run("api:app", host="0.0.0.0", port=port, log_config=None)
