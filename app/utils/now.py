from datetime import datetime
import pytz

def now():
    timezone = pytz.timezone('Asia/Taipei')

    return datetime.now(timezone).strftime('%Y-%m-%d %H:%M:%S')
