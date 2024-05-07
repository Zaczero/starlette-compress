# starlette-compress

[![Support my work](https://shields.monicz.dev/badge/%E2%99%A5%EF%B8%8F%20Support%20my%20work-purple)](https://monicz.dev/#support-my-work)
[![Liberapay Patrons](https://shields.monicz.dev/liberapay/patrons/Zaczero?logo=liberapay)](https://liberapay.com/Zaczero/)
![PyPI - Python Version](https://shields.monicz.dev/pypi/pyversions/starlette-compress)

**starlette-compress** is a fast and simple middleware for compressing responses in [Starlette](https://www.starlette.io). It supports more compression algorithms than Starlette's built-in GZipMiddleware, and has more sensible defaults.

- Python 3.8+ support
- Compatible with `asyncio` and `trio` backends
- ZStd, Brotli, and GZip compression
- Sensible default configuration
- [The Unlicense](https://unlicense.org) - public domain dedication
- [Semantic Versioning](https://semver.org) compliance

## Installation

```sh
pip install starlette-compress
```

## Example

### Starlette

```py
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette_compress import CompressMiddleware

middleware = [
    Middleware(CompressMiddleware)
]

app = Starlette(routes=..., middleware=middleware)
```

### FastAPI

starlette-compress is compatible with FastAPI.

```py
from fastapi import FastAPI
from starlette_compress import CompressMiddleware

app = FastAPI()
app.add_middleware(CompressMiddleware)
```

## Guide

### Changing the minimum length of the response to compress

To change the minimum length of the response to compress, use the `minimum_size` parameter. The default is 500 bytes.

```py
# Starlette
middleware = [
    Middleware(CompressMiddleware, minimum_size=1000)
]

# FastAPI
app.add_middleware(CompressMiddleware, minimum_size=1000)
```

### Registering a new content-type for compression

If you want to compress a content-type that is not registered by default, you can use the `register_compress_content_type` method.

```py
from starlette_compress import register_compress_content_type

register_compress_content_type("application/my-custom-type")
```

You can also exclude a content-type from being compressed with the `deregister_compress_content_type` method.

```py
from starlette_compress import deregister_compress_content_type

deregister_compress_content_type("application/my-custom-type")
```
