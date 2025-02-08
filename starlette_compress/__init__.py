from __future__ import annotations

import gzip
import re
from functools import lru_cache
from io import BytesIO
from platform import python_implementation
from typing import TYPE_CHECKING

from starlette.datastructures import Headers, MutableHeaders
from zstandard import ZstdCompressor

if python_implementation() == 'CPython' and not TYPE_CHECKING:
    try:
        import brotli
    except ModuleNotFoundError:
        import brotlicffi as brotli
else:
    try:
        import brotlicffi as brotli
    except ModuleNotFoundError:
        import brotli

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
    from zstandard import ZstdCompressionChunker


class CompressMiddleware:
    """Compression middleware for Starlette - supporting ZStd, Brotli, and GZip."""

    __slots__ = (
        '_brotli',
        '_gzip',
        '_identity',
        '_zstd',
        'app',
    )

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 500,
        zstd: bool = True,
        zstd_level: int = 4,
        brotli: bool = True,
        brotli_quality: int = 4,
        gzip: bool = True,
        gzip_level: int = 4,
    ) -> None:
        self.app = app
        self._zstd = _ZstdResponder(app, minimum_size, zstd_level) if zstd else None
        self._brotli = _BrotliResponder(app, minimum_size, brotli_quality) if brotli else None
        self._gzip = _GZipResponder(app, minimum_size, gzip_level) if gzip else None
        self._identity = _IdentityResponder(app, minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        accept_encoding = Headers(scope=scope).get('Accept-Encoding')
        if accept_encoding:
            accept_encodings = _parse_accept_encoding(accept_encoding)
            if (self._zstd is not None) and 'zstd' in accept_encodings:
                return await self._zstd(scope, receive, send)
            if (self._brotli is not None) and 'br' in accept_encodings:
                return await self._brotli(scope, receive, send)
            if (self._gzip is not None) and 'gzip' in accept_encodings:
                return await self._gzip(scope, receive, send)

        return await self._identity(scope, receive, send)


class _ZstdResponder:
    __slots__ = (
        'app',
        'compressor',
        'level',
        'minimum_size',
    )

    def __init__(self, app: ASGIApp, minimum_size: int, level: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.level = level
        self.compressor = ZstdCompressor(level=level)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_message: Message | None = None
        chunker: ZstdCompressionChunker | None = None

        async def wrapper(message: Message) -> None:
            nonlocal start_message, chunker

            message_type: str = message['type']

            # handle start message
            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError('Unexpected repeated http.response.start message')

                if _is_start_message_satisfied(message):
                    # capture start message and wait for response body
                    start_message = message
                    return
                else:
                    await send(message)
                    return

            # skip if start message is not satisfied or unknown message type
            if start_message is None or message_type != 'http.response.body':
                await send(message)
                return

            body: bytes = message.get('body', b'')
            more_body: bool = message.get('more_body', False)

            if chunker is None:
                # skip compression for small responses
                if not more_body and len(body) < self.minimum_size:
                    await send(start_message)
                    await send(message)
                    return

                headers = MutableHeaders(raw=start_message['headers'])
                headers['Content-Encoding'] = 'zstd'
                headers.add_vary_header('Accept-Encoding')

                if not more_body:
                    # one-shot
                    compressed_body = self.compressor.compress(body)
                    headers['Content-Length'] = str(len(compressed_body))
                    message['body'] = compressed_body
                    await send(start_message)
                    await send(message)
                    return

                # begin streaming
                content_length: int = int(headers.get('Content-Length', -1))
                del headers['Content-Length']
                await send(start_message)
                chunker = ZstdCompressor(level=self.level).chunker(content_length)

            # streaming
            for chunk in chunker.compress(body):
                await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
            if more_body:
                return
            for chunk in chunker.finish():  # type: ignore[no-untyped-call]
                await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})

            await send({'type': 'http.response.body'})

        await self.app(scope, receive, wrapper)


class _BrotliResponder:
    __slots__ = (
        'app',
        'minimum_size',
        'quality',
    )

    def __init__(self, app: ASGIApp, minimum_size: int, quality: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.quality = quality

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_message: Message | None = None
        compressor: brotli.Compressor | None = None

        async def wrapper(message: Message) -> None:
            nonlocal start_message, compressor

            message_type: str = message['type']

            # handle start message
            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError('Unexpected repeated http.response.start message')

                if _is_start_message_satisfied(message):
                    # capture start message and wait for response body
                    start_message = message
                    return
                else:
                    await send(message)
                    return

            # skip if start message is not satisfied or unknown message type
            if start_message is None or message_type != 'http.response.body':
                await send(message)
                return

            body: bytes = message.get('body', b'')
            more_body: bool = message.get('more_body', False)

            if compressor is None:
                # skip compression for small responses
                if not more_body and len(body) < self.minimum_size:
                    await send(start_message)
                    await send(message)
                    return

                headers = MutableHeaders(raw=start_message['headers'])
                headers['Content-Encoding'] = 'br'
                headers.add_vary_header('Accept-Encoding')

                if not more_body:
                    # one-shot
                    compressed_body: bytes = brotli.compress(body, quality=self.quality)
                    headers['Content-Length'] = str(len(compressed_body))
                    message['body'] = compressed_body
                    await send(start_message)
                    await send(message)
                    return

                # begin streaming
                del headers['Content-Length']
                await send(start_message)
                compressor = brotli.Compressor(quality=self.quality)

            # streaming
            chunk = compressor.process(body)
            if chunk:
                await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
            if more_body:
                return
            chunk = compressor.finish()
            await send({'type': 'http.response.body', 'body': chunk})

        await self.app(scope, receive, wrapper)


class _GZipResponder:
    __slots__ = (
        'app',
        'level',
        'minimum_size',
    )

    def __init__(self, app: ASGIApp, minimum_size: int, level: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_message: Message | None = None
        compressor: gzip.GzipFile | None = None
        buffer: BytesIO | None = None

        async def wrapper(message: Message) -> None:
            nonlocal start_message, compressor, buffer

            message_type: str = message['type']

            # handle start message
            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError('Unexpected repeated http.response.start message')

                if _is_start_message_satisfied(message):
                    # capture start message and wait for response body
                    start_message = message
                    return
                else:
                    await send(message)
                    return

            # skip if start message is not satisfied or unknown message type
            if start_message is None or message_type != 'http.response.body':
                await send(message)
                return

            body: bytes = message.get('body', b'')
            more_body: bool = message.get('more_body', False)

            if compressor is None:
                # skip compression for small responses
                if not more_body and len(body) < self.minimum_size:
                    await send(start_message)
                    await send(message)
                    return

                headers = MutableHeaders(raw=start_message['headers'])
                headers['Content-Encoding'] = 'gzip'
                headers.add_vary_header('Accept-Encoding')

                if not more_body:
                    # one-shot
                    compressed_body = gzip.compress(body, compresslevel=self.level)
                    headers['Content-Length'] = str(len(compressed_body))
                    message['body'] = compressed_body
                    await send(start_message)
                    await send(message)
                    return

                # begin streaming
                del headers['Content-Length']
                await send(start_message)
                buffer = BytesIO()
                compressor = gzip.GzipFile(mode='wb', compresslevel=self.level, fileobj=buffer)

            if buffer is None:
                raise AssertionError('Compressor is set but buffer is not')

            # streaming
            compressor.write(body)
            if not more_body:
                compressor.close()
            compressed_body = buffer.getvalue()
            if more_body:
                if compressed_body:
                    buffer.seek(0)
                    buffer.truncate()
                else:
                    return
            await send(
                {
                    'type': 'http.response.body',
                    'body': compressed_body,
                    'more_body': more_body,
                }
            )

        await self.app(scope, receive, wrapper)


class _IdentityResponder:
    __slots__ = (
        'app',
        'minimum_size',
    )

    def __init__(self, app: ASGIApp, minimum_size: int) -> None:
        self.app = app
        self.minimum_size = minimum_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_message: Message | None = None
        headers_set: bool = False

        async def wrapper(message: Message) -> None:
            nonlocal start_message, headers_set

            message_type: str = message['type']

            # handle start message
            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError('Unexpected repeated http.response.start message')

                if _is_start_message_satisfied(message):
                    # capture start message and wait for response body
                    start_message = message
                    return
                else:
                    await send(message)
                    return

            # skip if start message is not satisfied or unknown message type
            if start_message is None or message_type != 'http.response.body':
                await send(message)
                return

            if not headers_set:
                body: bytes = message.get('body', b'')
                more_body: bool = message.get('more_body', False)

                # skip compression for small responses
                if not more_body and len(body) < self.minimum_size:
                    await send(start_message)
                    await send(message)
                    return

                headers = MutableHeaders(raw=start_message['headers'])
                headers.add_vary_header('Accept-Encoding')
                await send(start_message)
                headers_set = True

            await send(message)

        await self.app(scope, receive, wrapper)


_accept_encoding_re = re.compile(r'[a-z]{2,8}')


@lru_cache(maxsize=128)
def _parse_accept_encoding(accept_encoding: str) -> frozenset[str]:
    """Parse the accept encoding header and return a set of supported encodings.

    >>> _parse_accept_encoding('br;q=1.0, gzip;q=0.8, *;q=0.1')
    {'br', 'gzip'}
    """
    return frozenset(_accept_encoding_re.findall(accept_encoding))


# Based on
# - https://github.com/h5bp/server-configs-nginx/blob/main/h5bp/web_performance/compression.conf#L38
# - https://developers.cloudflare.com/speed/optimization/content/compression/
_compress_content_types: set[str] = {
    'application/atom+xml',
    'application/eot',
    'application/font',
    'application/font-sfnt',
    'application/font-woff',
    'application/geo+json',
    'application/gpx+xml',
    'application/graphql+json',
    'application/javascript',
    'application/javascript-binast',
    'application/json',
    'application/ld+json',
    'application/manifest+json',
    'application/opentype',
    'application/otf',
    'application/rdf+xml',
    'application/rss+xml',
    'application/truetype',
    'application/ttf',
    'application/vnd.api+json',
    'application/vnd.mapbox-vector-tile',
    'application/vnd.ms-fontobject',
    'application/wasm',
    'application/x-httpd-cgi',
    'application/x-javascript',
    'application/x-opentype',
    'application/x-otf',
    'application/x-perl',
    'application/x-protobuf',
    'application/x-ttf',
    'application/x-web-app-manifest+json',
    'application/xhtml+xml',
    'application/xml',
    'font/eot',
    'font/otf',
    'font/ttf',
    'font/x-woff',
    'image/bmp',
    'image/svg+xml',
    'image/vnd.microsoft.icon',
    'image/x-icon',
    'multipart/bag',
    'multipart/mixed',
    'text/cache-manifest',
    'text/calendar',
    'text/css',
    'text/html',
    'text/javascript',
    'text/js',
    'text/markdown',
    'text/plain',
    'text/richtext',
    'text/vcard',
    'text/vnd.rim.location.xloc',
    'text/vtt',
    'text/x-component',
    'text/x-cross-domain-policy',
    'text/x-java-source',
    'text/x-markdown',
    'text/x-script',
    'text/xml',
}


def add_compress_type(content_type: str) -> None:
    """Add a new content-type to be compressed."""
    _compress_content_types.add(content_type)


def remove_compress_type(content_type: str) -> None:
    """Remove a content-type from being compressed."""
    _compress_content_types.discard(content_type)


def _is_start_message_satisfied(message: Message) -> bool:
    """Check if response should be compressed based on the start message."""
    headers = Headers(raw=message['headers'])

    # must not already be compressed
    if 'Content-Encoding' in headers:
        return False

    # content-type header must be present
    content_type = headers.get('Content-Type')
    if not content_type:
        return False

    # must be a compressible content-type
    basic_content_type = content_type.split(';', maxsplit=1)[0].strip()
    return basic_content_type in _compress_content_types


__all__ = (
    'CompressMiddleware',
    'add_compress_type',
    'remove_compress_type',
)
