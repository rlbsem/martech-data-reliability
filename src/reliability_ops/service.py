import argparse
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["source", "console"])
    p.add_argument("--config", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    a = p.parse_args()
    from pathlib import Path

    config = json.loads(Path(a.config).read_bytes())
    if a.mode == "source":
        from .source import serve
    else:
        from .console import serve
    with serve(config, a.host, a.port) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
