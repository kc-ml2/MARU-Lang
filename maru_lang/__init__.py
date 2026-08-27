"""MARU filesystem retrieval server."""

__version__ = "0.0.0"

from maru_lang.app import create_app

# Uvicorn factory mode avoids reading required environment variables merely by
# importing the package: `uvicorn --factory maru_lang:create_app`.
__all__ = ["create_app", "__version__"]
