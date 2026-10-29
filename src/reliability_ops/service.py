import argparse
import json


def validate_config(config, mode):
    from .common import OWNERS
    from .client import Client

    if mode == "console":
        if set(config) != {"state", "sources"} or set(config["sources"]) != set(OWNERS):
            raise ValueError("exact_read_only_configuration_required")
        for name, source in config["sources"].items():
            if set(source) != {"service", "url", "read_token"} or source["service"] != name:
                raise ValueError("read_only_source_identity_required")
            Client(source)
            if not isinstance(source["read_token"], str) or len(source["read_token"]) < 32:
                raise ValueError("strong_service_credential_required")
    else:
        if config["service"] not in OWNERS:
            raise ValueError("unknown_source_identity")
        tokens = [config[k] for k in ["read_token", "ack_token"]]
        if any(not isinstance(t, str) or len(t) < 32 for t in tokens) or tokens[0] == tokens[1]:
            raise ValueError("distinct_strong_scoped_credentials_required")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["source", "console"])
    p.add_argument("--config", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    a = p.parse_args()
    from pathlib import Path

    config = json.loads(Path(a.config).read_bytes())
    validate_config(config, a.mode)
    if a.mode == "source":
        from .source import serve
    else:
        from .console import serve
    with serve(config, a.host, a.port) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
