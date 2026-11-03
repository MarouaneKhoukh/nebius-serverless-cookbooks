"""Container health: both public gateways must be ready; never runs inference."""
import sys
import urllib.request


def main():
    for port in (8000, 8001):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status != 200:
                    return 1
        except Exception:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
