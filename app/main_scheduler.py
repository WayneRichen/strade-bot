from apscheduler.schedulers.blocking import BlockingScheduler
from app.worker_jobs import run_strategy_tick_job


def enqueue_strategy_job():
    """實際丟 RQ job 的函式，每次被 scheduler 呼叫一次"""
    strategy_id = 1  # 目前先寫死策略 1，要之後再改成動態可以再調整
    print(f"[Scheduler] 丟策略 job: strategy_id={strategy_id}")
    run_strategy_tick_job(strategy_id)


def main():
    # 用 BlockingScheduler，程式會常駐跑
    scheduler = BlockingScheduler(timezone="Asia/Taipei")

    # 每「整點」執行一次
    # minute=0 表示 00 分，hour='*' 表示每個小時
    scheduler.add_job(
        enqueue_strategy_job,
        "cron",
        minute=0,
        id="run_strategy_tick_hourly",
        replace_existing=True,
    )

    print("[Scheduler] APScheduler 啟動，將在每個整點丟策略 job")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[Scheduler] 收到停止訊號，結束")


if __name__ == "__main__":
    main()
