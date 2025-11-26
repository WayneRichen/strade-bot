🧩 專案簡介
-------

Strade Bot 是一套用 Python 撰寫、採用 CCXT 執行永續合約下單的量化交易系統。\
系統結構包含：

-   **策略層（Strategy）**：定時抓行情 → 計算買賣訊號 → 丟給 queue

-   **Bot 跟單系統（Bots）**：依照策略訊號自動下單

-   **交易執行層（Trade Service）**：自動開倉 / 平倉 → 寫入資料庫

-   **訂單狀態輪詢（Check Order Job）**：確認交易所訂單是否完全成交

-   **排程（Scheduler）+ 非同步任務（RQ Worker）**：支援多 Worker 併發

目前已支援：

✔ 開倉\
✔ 平倉\
✔ 檢查訂單狀態\
✔ 多交易所（binance / bitget / okx）\
✔ 多 Worker 並行下單\
✔ 延遲 Job（enqueue_in）\
✔ Sandbox 測試模式

* * * * *

📂 **專案目錄結構**
```
strade-bot/
│
├── app/
│   ├── main_scheduler.py        # 每整點跑策略 → 丟 run_strategy_tick_job
│   ├── worker.py                # RQ Worker 主程式（with_scheduler=True）
│   ├── worker_jobs.py           # Queue Job 入口（開倉 / 平倉 / 查單）
│   │
│   ├── strategies/              # 策略邏輯
│   │   ├── __init__.py
│   │   └── btcusdt_breakout.py  # 範例策略（突破策略）
│   │
│   ├── services/                # 商業邏輯
│   │   ├── __init__.py
│   │   ├── strategy_service.py  # 跑策略、寫入 strategy_trades
│   │   ├── bot_service.py       # 撈出使用策略的 bots
│   │   └── trade_service.py     # 開倉 / 平倉 / 查 order / 寫 DB
│   │
│   ├── exchange/
│   │   ├── __init__.py
│   │   └── exchange_factory.py  # 動態生成 ccxt client
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── db.py                # DB wrapper（with get_db() 自動關閉連線）
│   │   └── redis_client.py      # Redis 連線（RQ 用 binary mode）
│   │
│   └── __init__.py
│
├── logs/                        # Worker / Scheduler log 輸出
│
├── pyproject.toml               # Poetry 設定
└── README.md                    # 本檔案

```

* * * * *

⚙️ **環境需求**
===========

-   Python 3.11+

-   Poetry

-   Redis（RQ queue 用）

-   MySQL 5.7+ / MariaDB 10+

-   CCXT（交易所 API）

-   RQ（非同步工作佇列）

* * * * *

🚀 **安裝**
=========

### 1\. 安裝依賴

`poetry install`

### 2\. 安裝 Redis

macOS：

`brew install redis
brew services start redis`

Linux：

`sudo apt install redis-server
sudo systemctl enable redis --now`

### 3\. 建 MySQL 資料庫

`create database strade;`

* * * * *

🧠 **系統流程總覽**
=============

```
[main_scheduler] 每整點觸發
       ↓
run_strategy_tick_job(strategy_id)
       ↓
strategy_service.run_strategy()
       ↓
產生買賣訊號 & 建 strategy_trades
       ↓
get_bots_for_strategy() 撈出所有 bot
       ↓
每個 bot enqueue(run_bot_trade_job)
       ↓
worker 取 job → run_bot_trade()
       ↓
寫入 user_trades, user_trade_orders
       ↓
enqueue_in(3 秒, check_order_status_job)
       ↓
worker 取 job → 檢查訂單狀態
       ↓
完全成交 → user_trades.status = OPEN
平倉成交 → user_trades.status = CLOSED

```

* * * * *

🕹️ **啟動 Worker（支援延遲排程）**
=========================

RQ 要讓 `enqueue_in()` 正常運作，\
worker 一定要使用 `with_scheduler=True`。

你的 worker.py 已經長這樣：

`worker.work(with_scheduler=True)`

所以直接啟動即可：

`poetry run python -m app.worker`

> 建議同時開多個 worker，才能做到多 bot 併發下單：

```
poetry run python -m app.worker
poetry run python -m app.worker
poetry run python -m app.worker
```

* * * * *

⏰ **啟動 Scheduler（每整點跑策略）**
==========================

本系統的 scheduler 就是：

`app/main_scheduler.py`

手動執行：

`poetry run python -m app.main_scheduler`

正式自動化（crontab）：

`0 * * * * cd /path/to/strade-bot && poetry run python -m app.main_scheduler >> logs/scheduler.log 2>&1`

* * * * *

🎯 **主要 Job 一覽**
================

### ✔ 開倉（OPEN）

`run_bot_trade_job(bot_id, signal)`

-   呼叫交易所 create_order(open)

-   新增 user_trades（PENDING）

-   新增 user_trade_orders（OPEN）

-   enqueue_in(3 秒) → check_order_status_job

### ✔ 平倉（CLOSE）

`run_bot_close_trade_job(bot_id, signal)`

-   create_order(close)

-   user_trades → CLOSING

-   新增 user_trade_orders（CLOSE）

-   enqueue_in(3 秒) → check_order_status_job

### ✔ 檢查訂單（延遲任務）

`check_order_status_job(user_trade_id, exchange_order_id)`

-   呼叫交易所 fetch_order

-   更新 user_trade_orders

-   若 OPEN 完全成交 → user_trades.status = OPEN

-   若 CLOSE 完全成交 → user_trades.status = CLOSED（並計算 pnl）

* * * * *

🧪 **策略測試**
===========

你可以用以下方式丟策略 job：

`poetry run python -m app.main_scheduler`

或只測 bot 下單：

```python
from rq import Queue
from app.worker_jobs import run_bot_trade_job
from app.utils.redis_client import redis_conn

q = Queue("default", connection=redis_conn)
q.enqueue(run_bot_trade_job, 1, {"position_side": "LONG", "price": 87600, "trade_id": 10})
```
平倉：

```python
q.enqueue(run_bot_close_trade_job, 1, {"price": 87800})
```

* * * * *

📌 **注意事項（請務必看）**
=================

### 1\. worker 數量越多 → 下單越並行

但是 MySQL/Redis/交易所 API rate limit 也會是瓶頸。\
建議：

-   先開 2～4 個 worker

-   DB 都用 with get_db() 正確關連線 → 不會爆 max_connections

### 2\. sandbox_mode(True) 建議只在開發環境開

正式環境請務必改成 False。

### 3\. ccxt 不同交易所的參數可能不同

目前你是用 bitget → 已相容\
之後加 okx、binance、bybit 我可以一起幫你補完整 helper。