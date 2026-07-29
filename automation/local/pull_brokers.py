#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐席位拉取(2026-07-07): 五类席位的每一家成员单独取净持仓历史 → broker_today.json
供资金潮汐"各类资金净流向"下拉展开每家席位用。数据源/口径同 pull_cohorts(qhkch 游客接口)。
支持断点续跑: 已到目标日的 (品种,席位) 自动跳过。
"""
import json, sys, time, threading, logging, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import requests


D = Path(__file__).parent
OUT = D / "broker_today.json"
MEMBERS = {
    '机构': ['中信期货', '国泰君安', '东证期货'],
    '外资': ['乾坤期货', '摩根大通'],
    '杭州': ['永安期货', '南华期货', '浙商期货', '宝城期货', '物产中大', '大地期货'],
    '中财': ['中财期货'],
    '散户': ['东方财富期货', '徽商期货', '平安期货'],
}
GOLD_ONLY = {'中财期货'}            # 与分组口径一致: 中财只采金银
GOLD_VARS = ['沪金', '沪银']
VARIETIES = list(json.load(open(D / "varieties.json", encoding="utf-8")))
URL = "https://www.qhkch.com/ajax/variety_net_position.php?v=251011-1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Referer": "https://www.qhkch.com/",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
}
WORKERS = 3
PACE = 0.45

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(D / "logs" / f"brokers_{datetime.now():%Y%m%d_%H%M}.log", encoding='utf-8'),
              logging.StreamHandler(sys.stdout)], force=True)
log = logging.getLogger("brokers")

_tl = threading.local()


def sess():
    if not hasattr(_tl, "s"):
        s = requests.Session()
        try:
            s.get("https://www.qhkch.com/", headers=HEADERS, timeout=20)
        except Exception:
            pass
        _tl.s = s
    return _tl.s


def fetch(broker, variety, tries=4):
    body = urllib.parse.urlencode([("brokers[]", broker), ("variety", variety)])
    for a in range(1, tries + 1):
        try:
            r = sess().post(URL, headers=HEADERS, data=body, timeout=30)
            j = r.json()
            if j.get("code") == 0:
                return j
        except Exception as e:
            log.warning(f"  {variety}/{broker} 异常 {type(e).__name__}:{str(e)[:50]} 重试{a}/{tries}")
        time.sleep(min(2 * a, 8))
    return None


def main():
    out = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    # 目标日 = cohort_today.json 里机构的最新日期(与分组数据对齐)
    try:
        cd = json.loads((D / "cohort_today.json").read_text(encoding='utf-8'))
        target = max(cd[v]['机构']['dates'][-1] for v in cd if cd[v].get('机构', {}).get('dates'))
    except Exception:
        target = None
    log.info(f"目标日: {target}")

    all_brokers = [b for ms in MEMBERS.values() for b in ms]
    from datetime import date as _d
    monday = _d.today().weekday() == 0   # 周一全量刷新零仓对子(防漏新进场席位)
    tasks, skipped_zero = [], 0
    for b in all_brokers:
        vs = GOLD_VARS if b in GOLD_ONLY else VARIETIES
        for v in vs:
            cur = out.get(v, {}).get(b)
            if target and cur and cur.get("dates") and cur["dates"][-1] >= target:
                continue   # 已新鲜, 跳过
            if (not monday) and cur and cur.get("net") and all(x == 0 for x in cur["net"][-40:]):
                skipped_zero += 1
                continue   # 近40日全零=该席位不碰该品种, 非周一不刷(提速~23%)
            tasks.append((b, v))
    log.info(f"跳过零仓对子 {skipped_zero} 个 (周一={monday})")
    log.info(f"待采 {len(tasks)} 项(共 {len(all_brokers)} 席位)")

    lock = threading.Lock()
    done = ok = fail = 0

    def work(bv):
        b, v = bv
        j = fetch(b, v)
        time.sleep(PACE)
        return b, v, j

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(work, t) for t in tasks]
        for fu in as_completed(futs):
            b, v, j = fu.result()
            with lock:
                done += 1
                if j:
                    d = j.get("data", {})
                    dates = d.get("dates", [])
                    if dates:
                        out.setdefault(v, {})[b] = {
                            "dates": dates, "net": d.get("values", []),
                            "close": [(x[1] if x else None) for x in d.get("infos", [])]}
                        ok += 1
                    else:
                        fail += 1
                else:
                    fail += 1
                if done % 25 == 0:
                    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
                    log.info(f"[{done}/{len(tasks)}] ok={ok} fail={fail}")
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    log.info(f"完成: ok={ok} fail={fail} / {len(tasks)}")


if __name__ == "__main__":
    main()
