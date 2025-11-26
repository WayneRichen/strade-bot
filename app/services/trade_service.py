from app.utils.db import execute, get_db, query_one, insert_and_get_id
from app.exchange.exchange_factory import build_ccxt_client
import json
from ccxt.base.errors import ExchangeError


def run_bot_trade(bot_id, signal):
    with get_db() as db:
        bot = query_one(db, "SELECT * FROM bots WHERE id=%s", (bot_id,))
        account = query_one(
            db, "SELECT * FROM exchange_accounts WHERE id=%s", (bot["exchange_account_id"],))
        exchange = query_one(
            db, "SELECT * FROM exchanges WHERE id=%s", (account["exchange_id"],))

    params = json.loads(account["params"])

    print(f"[Bot {bot_id}] 使用交易所：{exchange['code']}")

    client = build_ccxt_client(
        exchange_code=exchange["code"],
        api_key=params.get("api_key"),
        secret_key=params.get("secret_key"),
        passphrase=params.get("passphrase"),
    )
    client.set_sandbox_mode(True)

    qty = float(bot["base_order_usdt"]) / signal["price"]

    print(f"[Bot {bot_id}] 下單 {signal['position_side']} {qty}")

    try:
        # 設定槓桿
        client.set_leverage(
            bot["leverage"],
            bot["exchange_symbol"],
            params={"marginMode": "isolated"},
        )
    except ExchangeError as e:
        print(f"[Bot {bot_id}] 設定槓桿失敗: {str(e)}")
        return None

    try:
        order = client.create_order(
            symbol=bot["exchange_symbol"],
            type='limit',
            side='buy',  # hedge_mode：多單 = buy
            amount=qty,
            price=signal["price"],
            params={
                'marginMode': 'isolated',
                'tradeSide': 'open',   # 開倉
            },
        )
    except ExchangeError as e:
        print(f"[Bot {bot_id}] 下單失敗: {str(e)}")
        return None

    print("交易所回應：", order)

    exchange_order_id = (
        order.get("id")
        or order.get("orderId")
        or order.get("info", {}).get("orderId")
    )
    order_status = order.get("status") or "NEW"
    filled = order.get("filled") or 0

    with get_db() as db:
        user_trade_sql = """
            INSERT INTO user_trades
            (user_id, strategy_trade_id, exchange_account_id, bot_id, exchange_symbol,
            position_side, quantity, leverage, entry_price, opened_at, status,
            created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, NOW(), %s,
                    NOW(), NOW())
        """

        user_trade_id = insert_and_get_id(
            db,
            user_trade_sql,
            (
                bot["user_id"],
                signal['trade_id'],
                bot["exchange_account_id"],
                bot['id'],
                bot['exchange_symbol'],
                signal['position_side'],
                qty,
                bot["leverage"],
                signal['price'],
                "PENDING",  # 一開始標 PENDING，等填單/成交再改
            ),
        )

        print(f"[Bot {bot_id}] 建立 user_trades.id = {user_trade_id}")

        order_sql = """
            INSERT INTO user_trade_orders
            (user_trade_id, exchange_order_id, type, price,
            requested_qty, filled_qty, status, raw_response,
            created_at, updated_at)
            VALUES (%s, %s, %s, %s,
                    %s, %s, %s, %s,
                    NOW(), NOW())
        """

        insert_and_get_id(
            db,
            order_sql,
            (
                user_trade_id,
                exchange_order_id,
                "OPEN",
                signal['price'],
                qty,
                float(filled),
                order_status,
                json.dumps(order),
            ),
        )

    print(f"[Bot {bot_id}] 已寫入 user_trade_orders (OPEN)")

    return {
        "user_trade_id": user_trade_id,
        "exchange_order_id": exchange_order_id,
        "order_status": order_status,
    }


def check_order_status(user_trade_id: int, exchange_order_id: str):
    print(
        f"[CheckOrder] 檢查 user_trade_id={user_trade_id} order={exchange_order_id}")

    # 1. 找 user_trades
    with get_db() as db:
        user_trade = query_one(
            db, "SELECT * FROM user_trades WHERE id=%s", (user_trade_id,))
        if not user_trade:
            print("[CheckOrder] user_trade 不存在")
            return

    # 2. 找 exchange_account
        account = query_one(
            db, "SELECT * FROM exchange_accounts WHERE id=%s", (
                user_trade["exchange_account_id"],)
        )
        exchange = query_one(
            db, "SELECT * FROM exchanges WHERE id=%s", (account["exchange_id"],)
        )

    params = json.loads(account["params"])

    client = build_ccxt_client(
        exchange_code=exchange["code"],
        api_key=params.get("api_key"),
        secret_key=params.get("secret_key"),
        passphrase=params.get("passphrase"),
    )
    client.set_sandbox_mode(True)

    # 3. 呼叫交易所查詢訂單狀態
    try:
        order = client.fetch_order(
            exchange_order_id, user_trade["exchange_symbol"])
    except Exception as e:
        print("fetch_order 失敗：", e)
        return

    print("[CheckOrder] 交易所回應：", order)

    # 解析 ccxt 訂單狀態
    status = (order.get("status") or "UNKNOWN").upper()
    filled = order.get("filled") or 0
    amount = order.get("amount") or None

    # 4. 更新 user_trade_orders
    with get_db() as db:
        sql = """
            UPDATE user_trade_orders
            SET requested_qty=%s, filled_qty=%s, status=%s, raw_response=%s, updated_at=NOW()
            WHERE user_trade_id=%s AND exchange_order_id=%s
        """
        execute(
            db,
            sql,
            (
                amount,
                filled,
                status,
                json.dumps(order),
                user_trade_id,
                exchange_order_id,
            ),
        )

        # 5. 如果完全成交，更新 user_trades.status = OPEN
        if status in ("CLOSED", "FILLED"):
            print(f"[CheckOrder] 訂單完全成交，更新 user_trade {user_trade_id} 為 OPEN")
            execute(
                db,
                """
                UPDATE user_trades
                SET quantity=%s, status='OPEN', opened_at=NOW(), updated_at=NOW()
                WHERE id=%s
                """,
                (amount, user_trade_id,),
            )
        else:
            print(f"[CheckOrder] 訂單狀態：{status}")

    return order
