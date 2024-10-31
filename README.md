# starlette-compress

[![PyPI - Python Version](https://shields.monicz.dev/pypi/pyversions/starlette-compress)](https://pypi.org/project/starlette-compress)
[![Liberapay Patrons](https://shields.monicz.dev/liberapay/patrons/Zaczero?logo=liberapay&label=Patrons)](https://liberapay.com/Zaczero/)
[![GitHub Sponsors](https://shields.monicz.dev/github/sponsors/Zaczero?logo=github&label=Sponsors&color=%23db61a2)](https://github.com/sponsors/Zaczero)

**starlette-compress** is a fast and simple middleware for compressing responses in [Starlette](https://www.starlette.io). It supports more compression algorithms than Starlette's built-in GZipMiddleware, and has more sensible defaults.

- Python 3.9+ support
- Compatible with `asyncio` and `trio` backends
- ZStd, Brotli, and GZip compression
- Sensible default configuration
- [The Unlicense](https://unlicense.org) — public domain dedication
- [Semantic Versioning](https://semver.org) compliance

## Installation

```sh
pip install starlette-compress
```

## Basic Usage

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

You can use starlette-compress with [FastAPI](https://fastapi.tiangolo.com) too:

```py
from fastapi import FastAPI
from starlette_compress import CompressMiddleware

app = FastAPI()
app.add_middleware(CompressMiddleware)
```

## Advanced Usage

### Changing Minimum Response Size

Control the minimum size of the response to compress. By default, responses must be at least 500 bytes to be compressed.

```py
# Starlette
middleware = [
    Middleware(CompressMiddleware, minimum_size=1000)
]

# FastAPI
app.add_middleware(CompressMiddleware, minimum_size=1000)
```

### Tuning Compression Levels

Adjust the compression levels for each algorithm. Higher levels mean smaller files but slower compression. Default level is 4 for all algorithms.

```py
# Starlette
middleware = [
    Middleware(CompressMiddleware, zstd_level=6, brotli_quality=6, gzip_level=6)
]

# FastAPI
app.add_middleware(CompressMiddleware, zstd_level=6, brotli_quality=6, gzip_level=6)
```

### Supporting Custom Content-Types

Manage the supported content-types. Unknown response types are not compressed. [Check here](https://github.com/Zaczero/starlette-compress/blob/main/starlette_compress/__init__.py) for the default configuration.

```py
from starlette_compress import add_compress_type, remove_compress_type

add_compress_type("application/my-custom-type")
remove_compress_type("application/json")
```
