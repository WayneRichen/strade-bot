from app.services.strategy_service import run_strategy
from app.services.bot_service import get_bots_for_strategy
from app.services.trade_service import run_bot_trade, check_order_status, close_bot_position

from rq import Queue
from app.utils.redis_client import redis_conn
from datetime import timedelta

q = Queue("default", connection=redis_conn)


def run_strategy_tick_job(strategy_id: int):
    print("=== 開始跑策略 Tick ===")

    # 呼叫策略服務，拿到訊號（可能是 OPEN / CLOSE / None）
    signal = run_strategy(strategy_id)

    if not signal:
        print("沒有訊號，結束。")
        return

    action = (signal.get("action") or "").upper()
    print(f"策略產生訊號：action={action}, side={signal.get('position_side')}, price={signal.get('price')}")

    # 抓這個策略底下所有 RUNNING 的 bots
    bots = get_bots_for_strategy(strategy_id)
    bot_count = len(bots)
    print(f"共 {bot_count} 個 bot 要處理")

    if bot_count == 0:
        print("沒有任何 RUNNING 的 bot，結束。")
        return

    # 依照 action 分流：OPEN → 開倉、CLOSE → 平倉
    if action == "OPEN":
        print("執行：OPEN 訊號，準備幫所有 bot 開倉")

        for bot in bots:
            bot_id = bot["id"]
            print(f"丟 bot 開倉 job: bot_id={bot_id}")
            q.enqueue(run_bot_trade_job, bot_id, signal)

    elif action in ("CLOSE", "TP_CLOSE", "SL_CLOSE"):
        print("執行：CLOSE 訊號，準備幫所有 bot 平倉")

        for bot in bots:
            bot_id = bot["id"]
            print(f"丟 bot 平倉 job: bot_id={bot_id}")
            q.enqueue(run_bot_close_trade_job, bot_id, signal)

    else:
        print(f"不支援的策略動作 action={action}，不處理。")
        return



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


def run_bot_close_trade_job(bot_id: int, signal: dict):
    """單一 bot 平倉 job"""
    result = close_bot_position(bot_id, signal)
    if not result:
        print(f"[Bot {bot_id}] 平倉失敗或沒有部位")
        return

    user_trade_id = result["user_trade_id"]
    exchange_order_id = result["exchange_order_id"]

    print(f"[Bot {bot_id}] 已建立平倉訂單，排程檢查訂單狀態 (CLOSE)")

    q.enqueue_in(
        timedelta(seconds=3),
        check_order_status_job,
        user_trade_id,
        exchange_order_id,
    )
