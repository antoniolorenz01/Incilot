import httpx


def client(base_url: str) -> httpx.AsyncClient:
    """HTTP client for the tools. Tests replace it with a mocked one."""
    return httpx.AsyncClient(base_url=base_url, timeout=10)
