from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the homelab status API")
    parser.add_argument("--host", default="10.0.1.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("homelab_status.api:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

