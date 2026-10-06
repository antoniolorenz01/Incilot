import httpx


def client(base_url: str) -> httpx.AsyncClient:
    """Cliente HTTP de las herramientas. Los tests lo reemplazan por uno simulado."""
    return httpx.AsyncClient(base_url=base_url, timeout=10)
