from app.utils.db import get_db, query_one

def breakout_strategy(price):
    with get_db() as db:
        strategy_trade = query_one(db, "SELECT * FROM strategy_trades WHERE id=1 AND exit_at is null")
        if strategy_trade:
            return {"position_side": "SHORT", "price": price}
        else:
            return {"position_side": "LONG", "price": price}
