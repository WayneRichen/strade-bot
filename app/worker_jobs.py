from app.services.strategy_service import run_strategy
from app.services.bot_service import get_bots_for_strategy
from app.services.trade_service import run_bot_trade, check_order_status

from rq import Queue
from app.utils.redis_client import redis_conn
from datetime import timedelta

q = Queue("default", connection=redis_conn)


def run_strategy_tick_job(strategy_id: int):
    print("=== 開始跑策略 Tick ===")
    signal = run_strategy(strategy_id)

    if not signal:
        print("沒有訊號，結束。")
        return

    print("策略產生訊號：", signal)

    bots = get_bots_for_strategy(strategy_id)
    print(f"共 {len(bots)} 個 bot 要處理")

    for bot in bots:
        print(f"丟 bot 下單 job: bot_id={bot['id']}")
        # 把 signal 一起丟進去，RQ 會幫你序列化
        q.enqueue(run_bot_trade_job, bot["id"], signal)


def run_bot_trade_job(bot_id: int, signal: dict):
    """單一 bot 執行下單邏輯"""
    result = run_bot_trade(bot_id, signal)

    if not result:
        print(f"[Bot {bot_id}] 下單失敗或被略過")
        return

    user_trade_id = result["user_trade_id"]
    exchange_order_id = result["exchange_order_id"]

    print(f"[Bot {bot_id}] 已建立 user_trade {user_trade_id}，排程檢查訂單狀態")

    q.enqueue_in(
        timedelta(seconds=3),
        check_order_status_job,
        user_trade_id,
        exchange_order_id,
    )


def check_order_status_job(user_trade_id: int, exchange_order_id: str):
    """延遲後執行，從交易所查訂單狀態，並更新 user_trade_orders & user_trades"""
    return check_order_status(user_trade_id, exchange_order_id)
