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
    print(f"[CheckOrder] 檢查 user_trade_id={user_trade_id} order={exchange_order_id}")

    # 1. 找 user_trades / account / exchange / 對應的 user_trade_order
    with get_db() as db:
        user_trade = query_one(
            db, "SELECT * FROM user_trades WHERE id=%s", (user_trade_id,)
        )
        if not user_trade:
            print("[CheckOrder] user_trade 不存在")
            return

        account = query_one(
            db,
            "SELECT * FROM exchange_accounts WHERE id=%s",
            (user_trade["exchange_account_id"],),
        )
        exchange = query_one(
            db, "SELECT * FROM exchanges WHERE id=%s", (account["exchange_id"],)
        )

        user_trade_order = query_one(
            db,
            """
            SELECT * FROM user_trade_orders
            WHERE user_trade_id=%s AND exchange_order_id=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_trade_id, exchange_order_id),
        )

    if not user_trade_order:
        print("[CheckOrder] 找不到對應的 user_trade_order")
        return

    order_type = user_trade_order["type"]  # OPEN / CLOSE

    params = json.loads(account["params"])

    client = build_ccxt_client(
        exchange_code=exchange["code"],
        api_key=params.get("api_key"),
        secret_key=params.get("secret_key"),
        passphrase=params.get("passphrase"),
    )
    client.set_sandbox_mode(True)

    # 2. 呼叫交易所查詢訂單狀態
    try:
        order = client.fetch_order(exchange_order_id, user_trade["exchange_symbol"])
    except Exception as e:
        print("fetch_order 失敗：", e)
        return

    print("[CheckOrder] 交易所回應：", order)

    status = (order.get("status") or "UNKNOWN").upper()
    filled = order.get("filled") or 0
    amount = order.get("amount") or None
    avg_price = order.get("average") or order.get("price") or user_trade_order["price"]

    # 3. 更新 user_trade_orders
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

        # 4. 依照訂單型別做不同處理
        if status in ("CLOSED", "FILLED"):
            if order_type == "OPEN":
                # 開倉完全成交
                print(f"[CheckOrder] 開倉完全成交，更新 user_trade {user_trade_id} 為 OPEN")
                execute(
                    db,
                    """
                    UPDATE user_trades
                    SET quantity=%s, status='OPEN', opened_at=NOW(), updated_at=NOW()
                    WHERE id=%s
                    """,
                    (amount, user_trade_id),
                )
            elif order_type == "CLOSE":
                # 平倉完全成交，計算損益
                print(f"[CheckOrder] 平倉完全成交，更新 user_trade {user_trade_id} 為 CLOSED")

                entry_price = float(user_trade["entry_price"])
                exit_price = float(avg_price)
                qty = float(user_trade["quantity"])
                side = user_trade["position_side"]  # LONG / SHORT

                if side == "LONG":
                    pnl = (exit_price - entry_price) * qty
                    pnl_pct = (exit_price / entry_price - 1) * 100
                else:
                    pnl = (entry_price - exit_price) * qty
                    pnl_pct = (entry_price / exit_price - 1) * 100

                execute(
                    db,
                    """
                    UPDATE user_trades
                    SET status='CLOSED',
                        closed_at=NOW(),
                        exit_price=%s,
                        pnl=%s,
                        pnl_pct=%s,
                        updated_at=NOW()
                    WHERE id=%s
                    """,
                    (exit_price, pnl, pnl_pct, user_trade_id),
                )
        else:
            print(f"[CheckOrder] 訂單狀態：{status}")

    return order


def close_bot_position(bot_id, signal: dict):
    """
    平倉流程：
    - 找出這個 bot 最新一筆 OPEN 的 user_trades
    - 依照 position_side 決定平倉方向（LONG -> sell, SHORT -> buy）
    - 建立交易所平倉訂單（tradeSide = close）
    - 新增一筆 user_trade_orders(type='CLOSE')
    - 將 user_trades.status 標記為 CLOSING（等查單後再標 CLOSED）
    """

    # 1. 先查 bot / user_trade / account / exchange
    with get_db() as db:
        bot = query_one(db, "SELECT * FROM bots WHERE id=%s", (bot_id,))
        if not bot:
            print(f"[Bot {bot_id}] 找不到 bot")
            return None

        # 找這個 bot 最新一筆 OPEN 的部位
        user_trade = query_one(
            db,
            """
            SELECT * FROM user_trades
            WHERE bot_id=%s AND status='OPEN'
            ORDER BY id DESC
            LIMIT 1
            """,
            (bot_id,),
        )
        if not user_trade:
            print(f"[Bot {bot_id}] 沒有 OPEN 部位，略過平倉")
            return None

        account = query_one(
            db,
            "SELECT * FROM exchange_accounts WHERE id=%s",
            (user_trade["exchange_account_id"],),
        )
        exchange = query_one(
            db,
            "SELECT * FROM exchanges WHERE id=%s",
            (account["exchange_id"],),
        )

    params = json.loads(account["params"])

    print(f"[Bot {bot_id}] 使用交易所：{exchange['code']} 進行平倉")

    client = build_ccxt_client(
        exchange_code=exchange["code"],
        api_key=params.get("api_key"),
        secret_key=params.get("secret_key"),
        passphrase=params.get("passphrase"),
    )
    client.set_sandbox_mode(True)

    # 要平掉的數量用 user_trades 的 quantity
    qty = float(user_trade["quantity"])
    position_side = user_trade["position_side"]  # LONG / SHORT
    symbol = user_trade["exchange_symbol"]

    # 關倉方向：多單平倉 = sell，空單平倉 = buy
    if position_side == "LONG":
        close_side = "buy"
    else:
        close_side = "sell"

    close_price = signal["price"]

    print(f"[Bot {bot_id}] 平倉 {position_side} {qty} @ {close_price} ({close_side})")

    # 真正平倉下單
    try:
        order = client.create_order(
            symbol=symbol,
            type="limit",
            side=close_side,
            amount=qty,
            price=close_price,
            params={
                "marginMode": "isolated",
                "tradeSide": "close",  # ★ 關倉
            },
        )
    except ExchangeError as e:
        print(f"[Bot {bot_id}] 平倉下單失敗：{str(e)}")
        return None

    print(f"[Bot {bot_id}] 平倉下單交易所回應：", order)

    exchange_order_id = (
        order.get("id")
        or order.get("orderId")
        or order.get("info", {}).get("orderId")
    )
    order_status = order.get("status") or "NEW"
    filled = order.get("filled") or 0

    # 2. 寫入 CLOSE 訂單 + 將 user_trades 狀態標為 CLOSING
    with get_db() as db:
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
                user_trade["id"],
                exchange_order_id,
                "CLOSE",
                close_price,
                qty,
                float(filled),
                order_status,
                json.dumps(order),
            ),
        )

        # 先把 user_trades 標記成 CLOSING，等查單後再設 CLOSED
        execute(
            db,
            """
            UPDATE user_trades
            SET status='CLOSING', exit_price=%s, updated_at=NOW()
            WHERE id=%s
            """,
            (user_trade["id"], close_price),
        )

    print(f"[Bot {bot_id}] 已寫入 user_trade_orders (CLOSE)，user_trade {user_trade['id']} 標記為 CLOSING")

    return {
        "user_trade_id": user_trade["id"],
        "exchange_order_id": exchange_order_id,
        "order_status": order_status,
    }