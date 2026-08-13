import time
from contextlib import contextmanager
from typing import Optional

from sqlalchemy.orm import Session

import models


def log_query(
    db: Session,
    query_text: str,
    path: str,
    latency_ms: float,
    result_count: int,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    success: bool = True,
    error: Optional[str] = None,
):
    entry = models.QueryLog(
        query_text=query_text,
        path=path,
        reason=reason,
        confidence=confidence,
        latency_ms=latency_ms,
        result_count=result_count,
        success=success,
        error=error,
    )
    db.add(entry)
    db.commit()


@contextmanager
def timed():
    """Usage: with timed() as t: ... ; then t() returns elapsed ms."""
    start = time.perf_counter()
    yield lambda: (time.perf_counter() - start) * 1000
