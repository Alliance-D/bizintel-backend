from collections.abc import Callable
from typing import Any


def enqueue_job(job_name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> dict:
    # Replace this local synchronous implementation with Redis/RQ/Celery/Arq in production.
    result = func(*args, **kwargs)
    return {'job_name': job_name, 'status': 'completed', 'result': result}
