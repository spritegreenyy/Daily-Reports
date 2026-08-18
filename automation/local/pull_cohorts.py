#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分组求和拉取(本地版 2026-07-07, 服务器重装后迁移): qhkch 游客接口(纯 requests, 无登录/验证码).
五类席位(机构/外资/杭州/中财/散户)按组一次调用自动求和, 输出 cohort_today.json:
{variety: {cohort: {dates, net, close}}} —— 与原服务器版格式完全一致。
"""
import argparse, json, sys, time, logging, urllib.parse
from datetime import datetime
from pathlib import Path
import requests

D = Path(__file__).parent
OUT = D / "cohort_today.json"
COHORTS = {
    '机构': ['中信期货', '国泰君安', '东证期货'],
    '外资': ['乾坤期货', '摩根大通'],
    '杭州': ['永安期货', '南华期货', '浙商期货', '宝城期货', '物产中大', '大地期货'],
    '散户': ['东方财富期货', '徽商期货', '平安期货'],
}
GOLD_COHORT = {'中财': ['中财期货']}
GOLD_VARS = ['沪金', '沪银']
VARIETIES = list(json.load(open(D / "varieties.json", encoding="utf-8")))

URL = "https://x.qhkch.com/ajax/variety_net_position"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Referer": "https://x.qhkch.com/variety/net_position",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
}
PACE = 0.5

(D / "logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(D / "logs" / f"cohort_{datetime.now():%Y%m%d_%H%M}.log", encoding='utf-8'),
              logging.StreamHandler(sys.stdout)], force=True)
log = logging.getLogger("cohort")


def body_for(brokers, variety):
    parts = [("brokers[]", b) for b in brokers] + [("variety", variety)]
    return urllib.parse.urlencode(parts)


def fetch(session, brokers, variety, tries=4):
    for a in range(1, tries + 1):
        try:
            r = session.post(URL, headers=HEADERS, data=body_for(brokers, variety), timeout=(10, 25))
            j = r.json()
            if j.get("code") == 0:
                return j
            log.info(f"  {variety} code={j.get('code')} msg={j.get('msg')} 重试{a}/{tries}")
        except Exception as e:
            log.warning(f"  {variety} 异常 {type(e).__name__}:{str(e)[:60]} 重试{a}/{tries}")
        time.sleep(min(2 * a, 8))
    return {"code": -1}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target-date",
        help="Lock the snapshot to YYYY-MM-DD; newer observations are trimmed.",
    )
    return parser.parse_args()


def trim_to_date(data, target):
    dates = data.get("dates", [])
    if not target or target not in dates:
        return data
    end = dates.index(target) + 1
    trimmed = dict(data)
    for key in ("dates", "values", "infos", "net_buy", "net_ss"):
        if isinstance(data.get(key), list):
            trimmed[key] = data[key][:end]
    return trimmed


def main():
    args = parse_args()
    out = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    s = requests.Session()
    try:
        s.get("https://x.qhkch.com/", headers=HEADERS, timeout=20)
    except Exception:
        pass
    # 断点续跑: 目标日=今天(只用于同日内重跑续传; 跨日必然重采, 修复"昨天已齐误判今天不用采"的bug)
    from datetime import date
    tgt = args.target_date or date.today().isoformat()
    ok = fail = 0
    for vi, v in enumerate(VARIETIES, 1):
        out.setdefault(v, {})
        groups = dict(COHORTS)
        if v in GOLD_VARS:
            groups = {**groups, **GOLD_COHORT}
        if tgt and all(out[v].get(c, {}).get("dates") and out[v][c]["dates"][-1] >= tgt for c in groups):
            continue
        for cname, members in groups.items():
            if tgt and out[v].get(cname, {}).get("dates") and out[v][cname]["dates"][-1] >= tgt:
                continue
            j = fetch(s, members, v)
            if j.get("code") != 0:
                fail += 1
                log.warning(f"[{vi}/{len(VARIETIES)}] {v}/{cname} 失败")
                continue
            d = trim_to_date(j.get("data", {}), args.target_date)
            dates = d.get("dates", [])
            vals = d.get("values", [])
            infos = d.get("infos", [])
            if not dates:
                log.info(f"[{vi}/{len(VARIETIES)}] {v}/{cname} 无数据")
                continue
            out[v][cname] = {"dates": dates, "net": vals, "close": [(x[1] if x else None) for x in infos]}
            ok += 1
            log.info(f"[{vi}/{len(VARIETIES)}] {v}/{cname} {len(dates)}天 末日{dates[-1]} 净{vals[-1]}")
            time.sleep(PACE)
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    log.info(f"完成: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
