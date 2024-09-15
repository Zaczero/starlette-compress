from __future__ import annotations

import functools
from typing import Any, Callable, Literal

import pytest
from starlette.testclient import TestClient

TestClientFactory = Callable[..., TestClient]


# https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on
@pytest.fixture
def test_client_factory(
    anyio_backend_name: Literal['asyncio', 'trio'],
    anyio_backend_options: dict[str, Any],
) -> TestClientFactory:
    return functools.partial(
        TestClient,
        backend=anyio_backend_name,
        backend_options=anyio_backend_options,
    )
