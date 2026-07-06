#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日报台·打包版生成器（发给带教/团队用）

把最近 N 个交易日的报告直接内嵌进一个 HTML 文件：
对方拿到这一个文件，双击用浏览器打开就能看，不需要网络、不需要其他文件。

用法：
    python3 build_bundle.py            # 默认最近 10 个交易日
    python3 build_bundle.py --days 20  # 最近 20 个交易日
    python3 build_bundle.py --all      # 全部历史（文件会比较大）

输出：日报站/发送包/日报台_<最新日期>.html
"""

import argparse
import base64
import copy
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote

from build_site import SITE_DIR, scan, render_page

OUT_DIR = SITE_DIR / "发送包"

# 如果配置了同步目录（公司共享盘/坚果云/OneDrive 等同步文件夹），
# 每次生成后会把 日报台_最新.html 覆盖写一份过去，带教那边打开同一个文件即是最新。
# 例：SYNC_DIR = Path("/Users/yinyue/Nutstore Files/日报共享")
SYNC_DIR = None

MIME = {
    "html": "text/html",
    "img": "image/png",
}


def pdf_to_pages(path: Path) -> list:
    """PDF 逐页转 JPEG（base64 列表）。Chrome 不渲染内嵌数据的 PDF，只能转图。"""
    if not shutil.which("pdftoppm"):
        raise SystemExit("缺少 pdftoppm，请先执行：brew install poppler")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-jpeg", "-jpegopt", "quality=78", "-r", "130",
             str(path), str(Path(tmp) / "p")],
            check=True,
        )
        pages = sorted(Path(tmp).glob("p-*.jpg"))
        return [base64.b64encode(p.read_bytes()).decode("ascii") for p in pages]


def embed(dates):
    """把每个类型的最优格式文件内嵌进数据，去掉 href。"""
    total = 0
    for d in dates:
        for t in d["types"]:
            best = t["files"][0]  # scan() 已按 网页版 > 长图 > PDF 排好序
            path = (SITE_DIR / unquote(best["href"])).resolve()
            total += path.stat().st_size
            if best["kind"] == "pdf":
                t["files"] = [{"label": "PDF", "kind": "pages",
                               "pages": pdf_to_pages(path)}]
                continue
            mime = MIME[best["kind"]]
            if best["kind"] == "img" and path.suffix.lower() in (".jpg", ".jpeg"):
                mime = "image/jpeg"
            t["files"] = [{
                "label": best["label"],
                "kind": best["kind"],
                "mime": mime,
                "b64": base64.b64encode(path.read_bytes()).decode("ascii"),
            }]
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10, help="打包最近多少个交易日（默认 10）")
    ap.add_argument("--all", action="store_true", help="打包全部历史")
    args = ap.parse_args()

    dates = copy.deepcopy(scan())  # scan 返回新→旧
    if not args.all:
        dates = dates[: args.days]

    raw = embed(dates)
    note = f"打包版 · 最近 {len(dates)} 个交易日 · "
    html_out = render_page(dates, note=note)

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"日报台_{dates[0]['date']}.html"
    out.write_text(html_out, encoding="utf-8")
    latest = OUT_DIR / "日报台_最新.html"
    latest.write_text(html_out, encoding="utf-8")

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"完成：{len(dates)} 天（{dates[-1]['date']} ~ {dates[0]['date']}），"
          f"原始资料 {raw/1024/1024:.1f}MB → 打包文件 {size_mb:.1f}MB")
    print(f"按日期存档：{out}")
    print(f"固定文件名：{latest}")

    if SYNC_DIR is not None:
        sync_dir = Path(SYNC_DIR)
        if sync_dir.is_dir():
            (sync_dir / "日报台_最新.html").write_text(html_out, encoding="utf-8")
            print(f"已同步到共享目录:{sync_dir / '日报台_最新.html'}")
        else:
            print(f"警告：同步目录不存在，跳过：{sync_dir}")


if __name__ == "__main__":
    main()
