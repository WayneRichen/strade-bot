from app.utils.db import get_db, query_all

def get_bots_for_strategy(strategy_id: int):
    with get_db() as db:
        bots = query_all(db, """
            SELECT * FROM bots
            WHERE strategy_id=%s AND status='RUNNING'
        """, (strategy_id,))
    return bots
