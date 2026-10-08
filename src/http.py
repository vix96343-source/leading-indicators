"""スクレイピング共通: User-Agent 明示・ホストごと 1 リクエスト/秒・失敗時リトライ 3 回。"""
import time
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; leading-indicators-dashboard/1.0; personal use)"
MIN_INTERVAL_SEC = 1.0
RETRIES = 3

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_access: dict[str, float] = {}


def get(url: str, timeout: int = 30) -> requests.Response:
    host = urlparse(url).netloc
    last_err = None
    for attempt in range(RETRIES):
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_access.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_access[host] = time.monotonic()
        try:
            r = _session.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise  # 404 はリトライしても変わらない
            last_err = e
        except requests.RequestException as e:
            last_err = e
        time.sleep(2 ** attempt)
    raise last_err
