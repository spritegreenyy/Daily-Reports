#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 KOL 交易观点交互网页(独立可打开 HTML)。
输入(均在 output/):
  content_<YMD>.json     日报编辑版(insights/unique/sections, 已中文+高亮)
  kol_tweets_<YMD>.json  当天原始推文(含 url/赞数/板块/语言)
  kol_zh_<YMD>.json      翻译/过滤表: {推文短id(source_id后6位): 中文译文 或 ""(=过滤掉)}
                         中文推文自动保留、无需入表; 英文推不在表中时回退原文。
输出: 日报/<YMD>/KOL观点_<YMD>.html
用法: python3 build_web.py 2026-07-03
"""
import json, re, os, sys

ROOT="/Users/yinyue/Downloads/JYWC海拓"
KD=ROOT+"/kol_digest"
OUT=KD+"/output"
TMPL=KD+"/scripts/kol_web_template.html"

TW_BOARD={"macro":("宏观经济","#5b8def","宏观"),"geopolitics":("地缘政治","#ec6f57","地缘"),
 "commodities":("大宗商品","#e0952f","大宗"),"weather":("天气气候","#33bfad","天气"),
 "ai_semis":("AI半导体","#b18ef0","AI")}
REP_BOARD={"宏观经济":"#5b8def","地缘政治":"#ec6f57","大宗商品":"#e0952f","股票":"#3fb36a","AI半导体":"#b18ef0","AI半导体科技":"#b18ef0","AI / 半导体":"#b18ef0","天气气候":"#33bfad"}

def main():
    date=sys.argv[1] if len(sys.argv)>1 else None
    if not date: print("用法: build_web.py YYYY-MM-DD"); return 2
    ymd=date.replace("-","")
    tw=json.load(open(f"{OUT}/kol_tweets_{ymd}.json",encoding="utf-8"))
    rep=json.load(open(f"{OUT}/content_{ymd}.json",encoding="utf-8"))
    zhp=f"{OUT}/kol_zh_{ymd}.json"
    zh=json.load(open(zhp,encoding="utf-8")) if os.path.exists(zhp) else {}

    tweets=[];kols=set();dropped=0
    for sec in tw["sections"]:
        bk=sec["key"] if sec["key"] in TW_BOARD else "macro"
        for t in sec["tweets"]:
            sid=t["source_id"].replace("tw_","")[-6:]
            lang=t.get("language","en")
            if lang=="zh":
                body=(t.get("body") or "").strip()
            elif sid in zh and zh[sid].strip():
                body=zh[sid].strip()
            else:
                body=(t.get("body") or "").strip()
                if not body:
                    dropped+=1; continue
            kols.add(t["handle"])
            tags=[x for x in t.get("tags",[]) if x!="viewpoint"][:3]
            tweets.append({"h":t["handle"],"tier":t.get("tier",2),"b":bk,
                "t":t.get("published_at","")[:16].replace("T"," "),"x":body,"u":t.get("url",""),
                "lk":t.get("likes",0),"rt":t.get("retweets",0),"rp":t.get("replies",0),
                "eng":t.get("engagement",0),"lang":lang,"tags":tags})

    meta={"date":date,"n_tweets":len(tweets),"n_kols":len(kols),"n_accounts":tw.get("active_accounts_count",0),
        "generated":tw.get("generated_at","")[:16].replace("T"," "),
        "title":rep.get("title",""),"window":rep.get("window",""),
        "subtitle":rep.get("subtitle_stat","")+"　·　英文推优先译中，缺失时保留原文"}
    report={"insights":rep.get("insights",[]),"unique":rep.get("unique",[]),"sections":rep.get("sections",[])}
    DATA={date:{"meta":meta,"report":report,"tweets":tweets}}
    boards={k:{"label":v[0],"color":v[1],"short":v[2]} for k,v in TW_BOARD.items()}
    payload=json.dumps({"data":DATA,"boards":boards,"repColors":REP_BOARD,"dates":[date]},ensure_ascii=False)

    tmpl=open(TMPL,encoding="utf-8").read()
    html=tmpl.replace("__PAYLOAD__",payload).replace("__DATE__",date)
    dst_dir=f"{ROOT}/日报/{ymd}"; os.makedirs(dst_dir,exist_ok=True)
    dst=f"{dst_dir}/KOL观点_{ymd}.html"
    open(dst,"w",encoding="utf-8").write(html)
    print(f"OK · 保留{len(tweets)}条 过滤{dropped}条 · {len(kols)}位KOL · -> {dst}")
    return 0

if __name__=="__main__":
    sys.exit(main())
