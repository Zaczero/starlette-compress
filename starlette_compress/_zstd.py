from __future__ import annotations

from compression.zstd import ZstdCompressor  # type: ignore
from starlette.datastructures import MutableHeaders

from starlette_compress._utils import is_start_message_satisfied

TYPE_CHECKING = False
if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ZstdResponder:
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
        self.compressor = ZstdCompressor(level)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_message: Message | None = None
        chunker: ZstdCompressor | None = None

        async def wrapper(message: Message) -> None:
            nonlocal start_message, chunker

            message_type: str = message['type']

            # handle start message
            if message_type == 'http.response.start':
                if start_message is not None:
                    raise AssertionError(
                        'Unexpected repeated http.response.start message'
                    )

                if is_start_message_satisfied(message):
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
                    compressed_body = self.compressor.compress(body, 2)
                    headers['Content-Length'] = str(len(compressed_body))
                    message['body'] = compressed_body
                    await send(start_message)
                    await send(message)
                    return

                # begin streaming
                del headers['Content-Length']
                await send(start_message)
                chunker = ZstdCompressor(self.level)

            # streaming
            chunk = chunker.compress(body)  # type: ignore
            if chunk:
                await send(
                    {'type': 'http.response.body', 'body': chunk, 'more_body': True}
                )
            if more_body:
                return
            chunk = chunker.flush()  # type: ignore
            await send({'type': 'http.response.body', 'body': chunk})

        await self.app(scope, receive, wrapper)
