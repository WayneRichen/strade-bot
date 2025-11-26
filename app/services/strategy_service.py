from ccxt import binance
from app.utils.db import get_db, query_one, insert_and_get_id
from app.strategies.btcusdt_breakout import breakout_strategy


def run_strategy(strategy_id):
    with get_db() as db:
        strategy = query_one(
            db, "SELECT * FROM strategies WHERE id=%s AND is_active=1", (strategy_id,))
    print("策略：", strategy["name"])

    # 拿最新價格
    client = binance()
    ticker = client.fetch_ticker("BTC/USDT")
    price = ticker["last"]

    print("最新 BTC 價格：", price)

    # 跑策略
    signal = breakout_strategy(price)

    if not signal:
        print("策略沒有訊號")
        return None

    # 寫入 strategy_trades
    sql = """
        INSERT INTO strategy_trades (strategy_id, position_side, entry_price, entry_at, status, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), 'OPEN', NOW(), NOW())
    """

    with get_db() as db:
        trade_id = insert_and_get_id(db, sql, (strategy_id, signal["position_side"], signal["price"]))

    signal["trade_id"] = trade_id

    print("產生策略主控單 strategy_trade_id:", trade_id)

    return signal
