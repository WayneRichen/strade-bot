import redis

redis_conn = redis.Redis(
    host="127.0.0.1",
    port=6379,
    db=0,
    decode_responses=False   # RQ 需要 binary
)
