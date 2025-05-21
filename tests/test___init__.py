import random
import sys
from typing import Callable

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import ASGIApp

from starlette_compress import (
    CompressMiddleware,
    add_compress_type,
    remove_compress_type,
)
from starlette_compress._utils import parse_accept_encoding

TestClientFactory = Callable[[ASGIApp], TestClient]


def test_compress_responses(test_client_factory: TestClientFactory):
    def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse('x' * 4000, status_code=200)

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200

        try:
            assert response.text == 'x' * 4000
        except AssertionError:
            # TODO: remove after new zstd support in httpx
            if encoding != 'zstd' or sys.version_info < (3, 14):
                raise
            from compression import zstd

            assert zstd.decompress(response.content) == b'x' * 4000

        assert response.headers['Content-Encoding'] == encoding
        assert int(response.headers['Content-Length']) < 4000
        assert response.headers['Vary'] == 'Accept-Encoding'


def test_compress_not_in_accept_encoding(test_client_factory: TestClientFactory):
    def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse('x' * 4000, status_code=200)

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)
    response = client.get('/', headers={'accept-encoding': 'identity'})
    assert response.status_code == 200
    assert response.text == 'x' * 4000
    assert 'Content-Encoding' not in response.headers
    assert int(response.headers['Content-Length']) == 4000
    assert response.headers['Vary'] == 'Accept-Encoding'


def test_compress_ignored_for_small_responses(test_client_factory: TestClientFactory):
    def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse('OK', status_code=200)

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200
        assert response.text == 'OK'
        assert 'Content-Encoding' not in response.headers
        assert int(response.headers['Content-Length']) == 2
        assert 'Vary' not in response.headers


@pytest.mark.parametrize(
    'chunk_size',
    [
        1,
        128 * 1024,  # 128KB
    ],
)
def test_compress_streaming_response(
    test_client_factory: TestClientFactory, chunk_size: int
):
    random.seed(42)
    chunk_count = 70

    def homepage(request: Request) -> StreamingResponse:
        async def generator(count: int):
            for _ in range(count):
                # enough entropy is required for successful chunks
                yield random.getrandbits(8 * chunk_size).to_bytes(chunk_size, 'big')

        streaming = generator(chunk_count)
        return StreamingResponse(streaming, status_code=200, media_type='text/plain')

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200

        try:
            assert len(response.content) == chunk_count * chunk_size
        except AssertionError:
            # TODO: remove after new zstd support in httpx
            if encoding != 'zstd' or sys.version_info < (3, 14):
                raise
            from compression import zstd

            assert len(zstd.decompress(response.content)) == chunk_count * chunk_size

        assert response.headers['Content-Encoding'] == encoding
        assert 'Content-Length' not in response.headers
        assert response.headers['Vary'] == 'Accept-Encoding'


def test_compress_ignored_for_responses_with_encoding_set(
    test_client_factory: TestClientFactory,
):
    def homepage(request: Request) -> StreamingResponse:
        async def generator(content: bytes, count: int):
            for _ in range(count):
                yield content

        streaming = generator(content=b'x' * 400, count=10)
        return StreamingResponse(
            streaming, status_code=200, headers={'Content-Encoding': 'test'}
        )

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': f'{encoding}, test'})
        assert response.status_code == 200
        assert response.text == 'x' * 4000
        assert response.headers['Content-Encoding'] == 'test'
        assert 'Content-Length' not in response.headers
        assert 'Vary' not in response.headers


def test_compress_ignored_for_missing_accept_encoding(
    test_client_factory: TestClientFactory,
):
    def homepage(request: Request) -> PlainTextResponse:
        return PlainTextResponse('x' * 4000, status_code=200)

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)
    response = client.get('/', headers={'accept-encoding': ''})
    assert response.status_code == 200
    assert response.text == 'x' * 4000
    assert 'Content-Encoding' not in response.headers
    assert int(response.headers['Content-Length']) == 4000
    assert response.headers['Vary'] == 'Accept-Encoding'


def test_compress_ignored_for_missing_content_type(
    test_client_factory: TestClientFactory,
):
    def homepage(request: Request) -> Response:
        return Response('x' * 4000, status_code=200, media_type=None)

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200
        assert response.text == 'x' * 4000
        assert 'Content-Encoding' not in response.headers
        assert int(response.headers['Content-Length']) == 4000
        assert 'Vary' not in response.headers


def test_compress_registered_content_type(test_client_factory: TestClientFactory):
    def homepage(request: Request) -> Response:
        return Response('x' * 4000, status_code=200, media_type='test/test')

    app = Starlette(
        routes=[Route('/', endpoint=homepage)],
        middleware=[Middleware(CompressMiddleware)],
    )

    client = test_client_factory(app)

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200
        assert 'Content-Encoding' not in response.headers
        assert int(response.headers['Content-Length']) == 4000
        assert 'Vary' not in response.headers

    add_compress_type('test/test')

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200
        assert response.headers['Content-Encoding'] == encoding
        assert int(response.headers['Content-Length']) < 4000
        assert response.headers['Vary'] == 'Accept-Encoding'

    remove_compress_type('test/test')

    for encoding in ('gzip', 'br', 'zstd'):
        response = client.get('/', headers={'accept-encoding': encoding})
        assert response.status_code == 200
        assert 'Content-Encoding' not in response.headers
        assert int(response.headers['Content-Length']) == 4000
        assert 'Vary' not in response.headers


def test_parse_accept_encoding():
    assert parse_accept_encoding('') == frozenset()
    assert parse_accept_encoding('gzip, deflate') == {'gzip', 'deflate'}
    assert parse_accept_encoding('br;q=1.0,gzip;q=0.8, *;q=0.1') == {'br', 'gzip'}
