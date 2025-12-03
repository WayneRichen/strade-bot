from app.services.strategy_service import run_strategy
from app.services.bot_service import get_bots_for_strategy
from app.services.trade_service import run_bot_trade, check_order_status, close_bot_position
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any
import os
import time
from dotenv import load_dotenv

load_dotenv()

# 可以用環境變數調整最大執行緒數
MAX_WORKERS = int(os.getenv("WORKER_MAX_THREADS", 10))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def run_strategy_tick_job(strategy_id: int) -> Dict[str, Any]:
    """
    策略排程入口：給 FastAPI / Cloud Run 呼叫用
    - 先跑策略拿訊號
    - 找出該策略底下所有 RUNNING 的 bots
    - 依 action (OPEN / CLOSE...) 多執行緒去跑 bot 下單 / 平倉
    """
    print("=== 開始跑策略 Tick ===")

    # 呼叫策略服務，拿到訊號（可能是 OPEN / CLOSE / None）
    signal = run_strategy(strategy_id)

    if not signal:
        print("沒有訊號，結束。")
        return {
            "status": "no_signal",
            "strategy_id": strategy_id,
        }

    action = (signal.get("action") or "").upper()
    print(
        f"策略產生訊號：action={action}, side={signal.get('position_side')}, price={signal.get('price')}")

    # 抓這個策略底下所有 RUNNING 的 bots
    bots = get_bots_for_strategy(strategy_id)
    bot_count = len(bots)
    print(f"共 {bot_count} 個 bot 要處理")

    if bot_count == 0:
        print("沒有任何 RUNNING 的 bot，結束。")
        return {
            "status": "no_running_bots",
            "strategy_id": strategy_id,
            "action": action,
        }

    futures = []

    # 依照 action 分流：OPEN → 開倉、CLOSE → 平倉
    if action == "OPEN":
        print("執行：OPEN 訊號，準備幫所有 bot 開倉")

        for bot in bots:
            bot_id = bot["id"]
            print(f"丟 bot 開倉 job（多執行緒）: bot_id={bot_id}")
            future = executor.submit(run_bot_trade_task, bot_id, signal)
            futures.append(future)

    elif action in ("CLOSE", "TP_CLOSE", "SL_CLOSE"):
        print("執行：CLOSE 訊號，準備幫所有 bot 平倉")

        for bot in bots:
            bot_id = bot["id"]
            print(f"丟 bot 平倉 job（多執行緒）: bot_id={bot_id}")
            future = executor.submit(run_bot_close_trade_task, bot_id, signal)
            futures.append(future)

    else:
        print(f"不支援的策略動作 action={action}，不處理。")
        return {
            "status": "unsupported_action",
            "strategy_id": strategy_id,
            "action": action,
        }

    # 等所有 thread 跑完再回應（這樣 Cloud Run 這次 request 會確定跑完）
    success_count = 0
    fail_count = 0

    for future in as_completed(futures):
        try:
            ok = future.result()
            if ok:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"[run_strategy_tick_job] 有 bot job 發生例外: {e}")
            fail_count += 1

    print(
        f"=== 完成策略 Tick: strategy_id={strategy_id}, "
        f"bots={bot_count}, success={success_count}, fail={fail_count} ==="
    )

    return {
        "status": "completed",
        "strategy_id": strategy_id,
        "action": action,
        "bot_count": bot_count,
        "success_count": success_count,
        "fail_count": fail_count,
    }


def run_bot_trade_task(bot_id: int, signal: dict) -> bool:
    """單一 bot 執行開倉邏輯（在 thread 裡跑）"""
    print(f"[Bot {bot_id}] 開始執行下單邏輯")
    result = run_bot_trade(bot_id, signal)

    if not result:
        print(f"[Bot {bot_id}] 下單失敗或被略過")
        return False

    user_trade_id = result["user_trade_id"]
    exchange_order_id = result["exchange_order_id"]

    print(f"[Bot {bot_id}] 已建立 user_trade {user_trade_id}，等待 1 秒後檢查訂單狀態")
    time.sleep(1)
    check_order_status_task(user_trade_id, exchange_order_id)
    return True


def run_bot_close_trade_task(bot_id: int, signal: dict) -> bool:
    """單一 bot 平倉 job（在 thread 裡跑）"""
    print(f"[Bot {bot_id}] 開始執行平倉邏輯")
    result = close_bot_position(bot_id, signal)

    if not result:
        print(f"[Bot {bot_id}] 平倉失敗或沒有部位")
        return False

    user_trade_id = result["user_trade_id"]
    exchange_order_id = result["exchange_order_id"]

    print(f"[Bot {bot_id}] 已建立平倉訂單，等待 1 秒後檢查訂單狀態 (CLOSE)")
    time.sleep(1)
    check_order_status_task(user_trade_id, exchange_order_id)
    return True


def check_order_status_task(user_trade_id: int, exchange_order_id: str):
    """從交易所查訂單狀態，並更新 user_trade_orders & user_trades"""
    return check_order_status(user_trade_id, exchange_order_id)
