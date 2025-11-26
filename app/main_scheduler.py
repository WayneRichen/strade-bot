from rq import Queue
from app.utils.redis_client import redis_conn
from app.worker_jobs import run_strategy_tick_job

q = Queue("default", connection=redis_conn)

if __name__ == "__main__":
    print("丟策略 job...")
    q.enqueue(run_strategy_tick_job, 1)
