from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import typer


class Upstream(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer deployment-test-key":
            self.send_error(401)
            return
        self.send_response(200)
        if request.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {
                "id": "chatcmpl-deployment",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "deployment-echo",
                "choices": [{"index": 0, "delta": {"content": "deployment ready"}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(2)
            chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "chatcmpl-deployment",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "deployment-echo",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "deployment ready"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                    }
                ).encode()
            )


def serve() -> None:
    ThreadingHTTPServer(("0.0.0.0", 9000), Upstream).serve_forever()  # noqa: S104 isolated test upstream reachable by Docker services


if __name__ == "__main__":
    typer.run(serve)
