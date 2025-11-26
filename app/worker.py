from rq import Worker, Queue
from app.utils.redis_client import redis_conn


def main():
    queue = Queue("default", connection=redis_conn)

    # 建 worker
    worker = Worker([queue], connection=redis_conn)

    # 關鍵：with_scheduler=True，讓 worker 順便處理 enqueue_in / enqueue_at 的排程
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
