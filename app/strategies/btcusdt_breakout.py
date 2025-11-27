from app.utils.db import get_db, query_one

def breakout_strategy(price):
    with get_db() as db:
        strategy_trade = query_one(db, "SELECT * FROM strategy_trades WHERE strategy_id=1 AND exit_at is null")
        if strategy_trade:
            return {"action": "CLOSE", "position_side": "LONG", "price": price}
        else:
            return {"action": "OPEN", "position_side": "LONG", "price": price}
