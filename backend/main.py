"""
main.py (compatibility entrypoint)
==================================

The application now lives in the `app` package. This shim keeps the
historical `uvicorn main:app` invocation working from the backend/
directory.
"""

import os

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
