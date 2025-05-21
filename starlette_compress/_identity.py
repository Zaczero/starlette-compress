from __future__ import annotations

from starlette.datastructures import MutableHeaders

from starlette_compress._utils import is_start_message_satisfied

TYPE_CHECKING = False
if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


class IdentityResponder:
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
