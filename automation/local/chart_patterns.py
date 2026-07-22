#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""枢轴几何法形态识别(本地重写版 2026-07-07)。
服务器重装后原 stock-ta/chart_patterns.py 丢失, 按相同接口重写; 只实现日报在用的四大类:
三角(上升/下降/对称) / 矩形 / 楔形(上升/下降) / 旗形(多空旗形+三角旗)。

接口(与原库一致, hourly_pattern_report 无需改动):
    detect_chart_patterns(df, atr_mult=1.0) -> [hit, ...]
    hit = {pattern, bias(bullish/bearish/neutral), confidence(0-1),
           key_points:[{bar,price,label}], neckline:{slope,intercept}|None,
           start_bar, end_bar}
bar 均为传入 df 的位置下标(0..n-1)。
方法: ATR 归一的 zigzag 枢轴 → 对窗口内枢轴高/低点分别最小二乘拟合上下轨 →
按两轨斜率(ATR/bar 单位)组合分类; 旗形另要求形态前有≥3ATR的旗杆。
置信度 = 基础0.55 + 触点数 + 拟合优度 + 长度合理性 + 旗杆强度, 上限0.95。
"""
import numpy as np
import pandas as pd

FLAT = 0.025          # |斜率|(ATR/bar) 低于此视为水平
MIN_H = 1.2           # 形态最小高度(ATR)
TOUCH_TOL = 0.38      # 触点判定容差(ATR)


def _atr(df, n=14):
    h, l, c = df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().bfill().values


def _pivots(df, atr, mult):
    """zigzag: 反向波动超过 mult*ATR 记一个枢轴, 返回 [(bar, price, 'H'|'L'), ...] 交替。"""
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    n = len(df)
    piv = []
    direction = 0          # 1=向上找高点, -1=向下找低点
    ext_i, ext_hi, ext_lo = 0, h[0], l[0]
    for i in range(1, n):
        th = mult * atr[i]
        if direction >= 0:
            if h[i] > ext_hi:
                ext_hi, ext_i = h[i], i
            if ext_hi - l[i] > th:          # 从高点回落 → 确认 H
                piv.append((ext_i, ext_hi, "H"))
                direction = -1
                ext_i, ext_lo = i, l[i]
                continue
        if direction <= 0:
            if l[i] < ext_lo:
                ext_lo, ext_i = l[i], i
            if h[i] - ext_lo > th:          # 从低点回升 → 确认 L
                piv.append((ext_i, ext_lo, "L"))
                direction = 1
                ext_i, ext_hi = i, h[i]
    # 去重保持交替
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == "H" and p[1] >= out[-1][1]) or (p[2] == "L" and p[1] <= out[-1][1]):
                out[-1] = p
            continue
        out.append(p)
    return out


def _fit(pts):
    """最小二乘直线; 返回 slope, intercept, rms残差。pts=[(x,y)]"""
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)
    if len(pts) == 1:
        return 0.0, float(ys[0]), 0.0
    A = np.vstack([xs, np.ones_like(xs)]).T
    (k, b), res, *_ = np.linalg.lstsq(A, ys, rcond=None)
    rms = float(np.sqrt(res[0] / len(pts))) if len(res) else 0.0
    return float(k), float(b), rms


def _touches(line, pts, tol):
    k, b = line
    return sum(1 for x, y in pts if abs(y - (k * x + b)) <= tol)


def _classify(win_piv, atr_e, close, mom20):
    """win_piv: 窗口枢轴; 返回 (pattern, bias, neckline_side) 或 None。"""
    highs = [(p[0], p[1]) for p in win_piv if p[2] == "H"]
    lows = [(p[0], p[1]) for p in win_piv if p[2] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    ku, bu, ru = _fit(highs)
    kl, bl, rl = _fit(lows)
    su, sl = ku / atr_e, kl / atr_e            # ATR/bar 归一斜率
    x0 = min(p[0] for p in win_piv); x1 = max(p[0] for p in win_piv)
    h0 = (ku * x0 + bu) - (kl * x0 + bl)       # 起点高度
    h1 = (ku * x1 + bu) - (kl * x1 + bl)       # 终点高度
    if max(h0, h1) < MIN_H * atr_e:
        return None
    conv = h1 < h0 * 0.75                      # 收敛
    trend_bias = "bullish" if mom20 > 0 else "bearish"
    flat_u, flat_l = abs(su) < FLAT, abs(sl) < FLAT
    if flat_u and sl > FLAT:
        return ("Ascending Triangle", "bullish", "U", (ku, bu), (kl, bl), ru, rl)
    if flat_l and su < -FLAT:
        return ("Descending Triangle", "bearish", "L", (ku, bu), (kl, bl), ru, rl)
    if su < -FLAT and sl > FLAT and conv:
        side = "U" if trend_bias == "bullish" else "L"
        return ("Symmetric Triangle", trend_bias, side, (ku, bu), (kl, bl), ru, rl)
    if flat_u and flat_l:
        side = "U" if trend_bias == "bullish" else "L"
        return ("Rectangle", trend_bias, side, (ku, bu), (kl, bl), ru, rl)
    if su > FLAT and sl > FLAT and sl > su and conv:
        return ("Rising Wedge", "bearish", "L", (ku, bu), (kl, bl), ru, rl)
    if su < -FLAT and sl < -FLAT and su < sl and conv:
        return ("Falling Wedge", "bullish", "U", (ku, bu), (kl, bl), ru, rl)
    return None


def _containment(df, x0, x1, lu, ll, tol):
    """整段K线被上下轨包住的比例(真实形态质量, 不受枢轴数少的过拟合影响)。"""
    hs = df["high"].values[x0:x1 + 1]; ls = df["low"].values[x0:x1 + 1]
    xs = np.arange(x0, x1 + 1)
    up = lu[0] * xs + lu[1]; dn = ll[0] * xs + ll[1]
    ok = (hs <= up + tol) & (ls >= dn - tol)
    return float(ok.mean()) if len(ok) else 0.0


def detect_chart_patterns(df, atr_mult=1.0):
    df = df.reset_index(drop=True)
    n = len(df)
    if n < 40:
        return []
    atr = _atr(df)
    close = df["close"].values.astype(float)
    piv = _pivots(df, atr, atr_mult)
    if len(piv) < 4:
        return []
    hits = []

    def mom(end_bar):
        s = max(0, end_bar - 20)
        return close[end_bar] - close[s]

    # ── 三角/矩形/楔形: 滑动枢轴窗口 ──
    for end in range(len(piv) - 1, 2, -1):
        for size in (4, 5, 6, 7):
            if end - size + 1 < 0:
                break
            wp = piv[end - size + 1: end + 1]
            x0, x1 = wp[0][0], wp[-1][0]
            if not (12 <= x1 - x0 <= 150):
                continue
            atr_e = float(atr[x1])
            r = _classify(wp, atr_e, close, mom(x1))
            if not r:
                continue
            pat, bias, side, lu, ll, ru, rl = r
            tol = TOUCH_TOL * atr_e
            tu = _touches(lu, [(p[0], p[1]) for p in wp if p[2] == "H"], tol)
            tl = _touches(ll, [(p[0], p[1]) for p in wp if p[2] == "L"], tol)
            contain = _containment(df, x0, x1, lu, ll, 0.0)   # 零容差硬包容: 一根越线都算破
            # 打分: 额外触点是主信号, 硬包容是稀缺质量项; 4触点最小结构封顶~0.53被过滤
            conf = (0.28 + 0.11 * max(0, tu + tl - 4) + 0.20 * contain
                    + (0.05 if 20 <= x1 - x0 <= 90 else 0.0))
            conf = min(conf, 0.95)
            nk = lu if side == "U" else ll
            hits.append({
                "pattern": pat, "bias": bias, "confidence": round(conf, 3),
                "key_points": [{"bar": p[0], "price": p[1], "label": p[2] + str(i + 1)} for i, p in enumerate(wp)],
                "neckline": {"slope": nk[0], "intercept": nk[1]},
                "start_bar": x0, "end_bar": x1,
            })
            break   # 该终点取最先命中的窗口

    # ── 旗形/三角旗: 旗杆 + 短整理 ──
    for end in range(len(piv) - 1, 2, -1):
        for size in (4, 5, 6):
            if end - size + 1 < 1:
                break
            wp = piv[end - size + 1: end + 1]
            x0, x1 = wp[0][0], wp[-1][0]
            if not (6 <= x1 - x0 <= 40):
                continue
            atr_e = float(atr[x1])
            pole_s = max(0, x0 - 30)
            pole = close[x0] - close[pole_s]
            if abs(pole) < 3.0 * atr_e:
                continue
            highs = [(p[0], p[1]) for p in wp if p[2] == "H"]
            lows = [(p[0], p[1]) for p in wp if p[2] == "L"]
            if len(highs) < 2 or len(lows) < 2:
                continue
            ku, bu, ru = _fit(highs); kl, bl, rl = _fit(lows)
            su, sl = ku / atr_e, kl / atr_e
            h1 = (ku * x1 + bu) - (kl * x1 + bl)
            if h1 > 3.0 * atr_e:
                continue
            up = pole > 0
            parallel = abs(su - sl) < FLAT * 2
            conv = h1 < ((ku * x0 + bu) - (kl * x0 + bl)) * 0.75
            counter = (su < FLAT and sl < FLAT) if up else (su > -FLAT and sl > -FLAT)
            if parallel and counter:
                pat = "Bull Flag" if up else "Bear Flag"
            elif conv:
                pat = "Bull Pennant" if up else "Bear Pennant"
            else:
                continue
            bias = "bullish" if up else "bearish"
            nk = (ku, bu) if up else (kl, bl)
            tol = TOUCH_TOL * atr_e
            extra = max(0, _touches((ku, bu), highs, tol) + _touches((kl, bl), lows, tol) - 4)
            contain = _containment(df, x0, x1, (ku, bu), (kl, bl), 0.0)
            conf = min(0.95, 0.26 + 0.14 * min(abs(pole) / (5 * atr_e), 1.0)
                       + 0.09 * extra + 0.20 * contain)
            hits.append({
                "pattern": pat, "bias": bias, "confidence": round(conf, 3),
                "key_points": [{"bar": p[0], "price": p[1], "label": p[2] + str(i + 1)} for i, p in enumerate(wp)]
                              + [{"bar": pole_s, "price": float(close[pole_s]), "label": "P0"}],
                "neckline": {"slope": nk[0], "intercept": nk[1]},
                "start_bar": x0, "end_bar": x1,
            })
            break

    # ── 去重: 区间重叠且同类, 留置信度最高 ──
    hits.sort(key=lambda h: -h["confidence"])
    kept = []
    for h in hits:
        dup = any(k["pattern"] == h["pattern"]
                  and min(k["end_bar"], h["end_bar"]) - max(k["start_bar"], h["start_bar"])
                  > 0.5 * (h["end_bar"] - h["start_bar"]) for k in kept)
        if not dup:
            kept.append(h)
    return kept
