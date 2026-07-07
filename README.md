# Daily-Reports

一个可视化的日报仓库：每天的研究日报按日期归档，`日报站` 生成网页面板（日报台），点开能看到日常做的项目的面板报告。

## 🔗 在线看

**打开这个网址即可，无需下载、无需登录：**

### 👉 https://spritegreenyy.github.io/Daily-Reports/

- 左侧选**日期**，顶部切**报告**（期货资金潮汐 / 期货形态 / KOL观点）。
- 全部是**交互网页**：可筛选、排序、搜索、点开明细；图表都内嵌，手机/电脑都能看。
- 每天下午收盘后更新当天最新一期。

> 想离线保存某天的报告：进 `日报/日期/` 点开对应 `.html` 文件 → 右上角 **Download raw file** 下载 → 双击用浏览器打开（自带全部图表，断网也能看）。

## 目录结构

```
日报/
  20260703/                 ← 一天一个文件夹，8位日期
    期货形态_20260703.pdf
    期货资金潮汐_长图_20260703.png
    KOL观点_20260703.pdf
    ...
日报站/
  build_site.py             ← 生成本地日报台 index.html
  build_bundle.py           ← 生成单文件打包版（发送包/日报台_最新.html）
  更新日报站.command         ← macOS 双击一键更新（含 git 提交推送）
```

## 每天怎么交日报（所有人一样）

1. `git pull`
2. 把你当天的报告放进 `日报/YYYYMMDD/`（没有就新建这个日期文件夹）
3. `git add 日报 && git commit -m "日报 YYYYMMDD" && git push`

文件名规范：`报告名_YYYYMMDD.pdf|html|png`，同名报告多格式会自动归为一组。
新类型的报告不用改代码，只要按 `报告名_日期.pdf` 命名放进日期文件夹，日报台会自动多出一个标签页。

## 生成日报台

```
cd 日报站
python3 build_site.py      # 本地浏览版 index.html（引用原文件，秒级）
python3 build_bundle.py    # 单文件打包版，默认最近10个交易日（PDF会逐页转图，需 brew install poppler）
```

macOS 上直接双击 `日报站/更新日报站.command` 即可完成全部步骤。
