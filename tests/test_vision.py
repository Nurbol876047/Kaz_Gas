import httpx

from app.config import get_settings
from app.vision import looks_like_gas_meter

RealAsyncClient = httpx.AsyncClient


def mock_gemini(monkeypatch, status_code=200, text="METER"):
    def handler(request):
        if status_code != 200:
            return httpx.Response(status_code, text="error")
        return httpx.Response(status_code, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    monkeypatch.setattr(
        "app.vision.httpx.AsyncClient",
        lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_skips_check_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    assert await looks_like_gas_meter(b"irrelevant") is None


async def test_confirms_meter_photo(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    mock_gemini(monkeypatch, text="METER")
    assert await looks_like_gas_meter(b"photo bytes") is True


async def test_rejects_non_meter_photo(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    mock_gemini(monkeypatch, text="NOT_METER")
    assert await looks_like_gas_meter(b"photo bytes") is False


async def test_returns_none_on_api_error(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")
    mock_gemini(monkeypatch, status_code=500)
    assert await looks_like_gas_meter(b"photo bytes") is None


async def test_returns_none_on_unexpected_response_shape(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-key")

    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    monkeypatch.setattr(
        "app.vision.httpx.AsyncClient",
        lambda **kwargs: RealAsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await looks_like_gas_meter(b"photo bytes") is None
