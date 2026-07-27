import time
from functools import wraps

from src.utils.logger import logger
from src.utils.metrics import NODE_DURATION_SECONDS, NODE_FAILURES_TOTAL


def log_node(node_name: str):
    """
    Decorator for logging LangGraph node execution, and (see
    src/utils/metrics.py) the single hook point for per-node Prometheus
    metrics -- every node already goes through this decorator, so
    instrumenting it here covers all of them without touching each node
    file individually.
    """

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            start_time = time.perf_counter()

            logger.info("=" * 80)
            logger.info(f"[START] Node: {node_name}")

            try:

                result = func(*args, **kwargs)

                elapsed = time.perf_counter() - start_time
                NODE_DURATION_SECONDS.labels(node=node_name).observe(elapsed)

                logger.info(f"[DONE] Node: {node_name}")
                logger.info(f"[TIME] {elapsed:.4f} sec")

                return result

            except Exception as e:

                elapsed = time.perf_counter() - start_time
                NODE_DURATION_SECONDS.labels(node=node_name).observe(elapsed)
                NODE_FAILURES_TOTAL.labels(node=node_name).inc()

                logger.exception(f"[FAILED] Node: {node_name}")
                logger.info(f"[TIME] Failed After : {elapsed:.4f} sec")

                raise

        return wrapper

    return decorator