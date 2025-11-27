from ccxt import binance
from app.utils.db import get_db, query_one, insert_and_get_id, execute
from app.strategies.btcusdt_breakout import breakout_strategy


def run_strategy(strategy_id: int):
    # 先抓策略資料
    with get_db() as db:
        strategy = query_one(
            db,
            "SELECT * FROM strategies WHERE id=%s AND is_active=1",
            (strategy_id,),
        )

    if not strategy:
        print(f"找不到策略 id={strategy_id} 或已停用")
        return None

    print("策略：", strategy["name"])

    # 拿最新價格（先假設都是 BTCUSDT，用 binance 現貨 / 合約 ticker）
    client = binance()
    ticker = client.fetch_ticker("BTC/USDT")
    price = ticker["last"]

    print("最新 BTC 價格：", price)

    # 跑策略，取得訊號
    signal = breakout_strategy(price)

    if not signal or not signal.get("action"):
        print("策略沒有訊號")
        return None

    action = signal["action"].upper()        # OPEN / CLOSE
    position_side = signal.get("position_side")  # LONG / SHORT
    signal["price"] = price                  # 保險一點，用實際 ticker 價

    # ---------- 處理 OPEN 訊號 ----------
    if action == "OPEN":
        # 寫入一筆新的 strategy_trades（開倉）
        sql = """
            INSERT INTO strategy_trades
            (strategy_id, position_side, entry_price, entry_at, status, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), 'OPEN', NOW(), NOW())
        """

        with get_db() as db:
            trade_id = insert_and_get_id(
                db,
                sql,
                (strategy_id, position_side, price),
            )

        signal["trade_id"] = trade_id

        print("產生策略主控單 (OPEN) strategy_trade_id:", trade_id)
        return signal

    # ---------- 處理 CLOSE 訊號 ----------
    if action == "CLOSE":
        # 找這個策略最新一筆未平倉的 strategy_trades
        with get_db() as db:
            open_trade = query_one(
                db,
                """
                SELECT * FROM strategy_trades
                WHERE strategy_id=%s AND status='OPEN'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (strategy_id,),
            )

        if not open_trade:
            print("沒有未平倉部位，略過 CLOSE 訊號")
            return None

        entry_price = float(open_trade["entry_price"])
        exit_price = price

        # 算損益 %
        pnl_pct = None
        side = position_side or open_trade.get("position_side")

        if side == "LONG":
            pnl_pct = (exit_price / entry_price - 1) * 100
        elif side == "SHORT":
            pnl_pct = (entry_price / exit_price - 1) * 100

        # 更新這筆 strategy_trade，補上 exit_price / exit_at / 狀態 / pnl_pct
        with get_db() as db:
            execute(
                db,
                """
                UPDATE strategy_trades
                SET exit_price=%s,
                    exit_at=NOW(),
                    status='CLOSED',
                    pnl_pct=%s,
                    updated_at=NOW()
                WHERE id=%s
                """,
                (exit_price, pnl_pct, open_trade["id"]),
            )

        signal["trade_id"] = open_trade["id"]

        print("平倉策略主控單 (CLOSE) strategy_trade_id:", open_trade["id"])
        return signal

    # 其他不認得的 action
    print(f"不支援的策略 action: {action}")
    return None
