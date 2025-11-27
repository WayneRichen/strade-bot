from app.utils.db import get_db, query_one
import pandas_ta as ta

def breakout_strategy(df):
    look_back = 32
    adx_period = 14
    adx_threshold = 25
    take_profit = 1.05

    df['adx'] = ta.adx(df['high'], df['low'], df['close'], length=adx_period)[f'ADX_{adx_period}']
    df['highest'] = df['high'].rolling(look_back).max().shift(1)
    df['lowest'] = df['low'].rolling(look_back).min().shift(1)

    adx = df['adx'].iloc[-1]
    price = df['close'].iloc[-1]
    highest = df['highest'].iloc[-1]
    lowest = df['lowest'].iloc[-1]
    regime = adx > adx_threshold

    with get_db() as db:
        last_order = query_one(db, "SELECT * FROM strategy_trades WHERE strategy_id=1 AND exit_at is null")

    # 停利條件
    if last_order and price > float(last_order['entry_price']) * take_profit:
        return {"action": "TP_CLOSE", "position_side": "LONG", "price": price}
    if regime:
        if (not last_order) and price > highest:
            return {"action": "OPEN", "position_side": "LONG", "price": price}
        elif last_order and price < lowest:
            return {"action": "CLOSE", "position_side": "LONG", "price": price}
        else:
            return None
    else:
        return None
