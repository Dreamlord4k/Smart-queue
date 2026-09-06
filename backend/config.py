import os


EMA_ALPHA = 0.3
ETA_RANGE_K = 1.0
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
