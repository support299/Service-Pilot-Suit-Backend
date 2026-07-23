"""Small helpers for consistent success responses."""
from __future__ import annotations

from typing import Any, Optional

from rest_framework import status
from rest_framework.response import Response


def ok(data: Any = None, *, status_code: int = status.HTTP_200_OK) -> Response:
    return Response(data if data is not None else {}, status=status_code)


def created(data: Any = None) -> Response:
    return ok(data, status_code=status.HTTP_201_CREATED)


def no_content() -> Response:
    return Response(status=status.HTTP_204_NO_CONTENT)


def message(text: str, *, status_code: int = status.HTTP_200_OK,
            extra: Optional[dict[str, Any]] = None) -> Response:
    body: dict[str, Any] = {"message": text}
    if extra:
        body.update(extra)
    return Response(body, status=status_code)
