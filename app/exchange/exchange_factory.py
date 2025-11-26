import ccxt

def build_ccxt_client(exchange_code, api_key, secret_key, passphrase=None):
    """
    exchange_code = exchanges.code
    ex: binance, bitget, okx, bybit
    """

    if not hasattr(ccxt, exchange_code):
        raise Exception(f"不支援的交易所: {exchange_code}")

    exchange_class = getattr(ccxt, exchange_code)

    params = {
        "apiKey": api_key,
        "secret": secret_key,
        "enableRateLimit": True,
    }

    if passphrase:
        params["password"] = passphrase  # bitget / okx 用

    return exchange_class(params)
