#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
audit_package.py — 投稿包终检

查：白名单合规、内部文件残留、乱码文件名、BOM、图分辨率/色彩、文件可读性

用法:
    python audit_package.py --package 包目录
    python audit_package.py --package 包目录 --whitelist ok.txt   # 每行一个相对路径
    python audit_package.py --package 包目录 --init-whitelist     # 生成当前清单为白名单
"""
import argparse
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

R = []
def add(level, label, detail=""):
    R.append({"level": level, "label": label, "detail": detail})

# 内部文件特征
INTERNAL_PAT = re.compile(
    r"(TODO|TO_DO|待办|笔记|note[s]?_|draft|草稿|临时|temp|backup|~\$"
    r"|步骤|步骤说明|操作指引|readme_?internal|需知)", re.I)

# 本机路径特征（文件内容里出现即警告）
LOCALPATH_PAT = re.compile(r"[A-Za-z]:\\(?:Users|workbuddy|stiffness|data)|/Users/|C:/Users/")

def scan_content_for_localpaths(path, max_bytes=200_000):
    """扫文本类文件是否含本机路径"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".md", ".txt", ".py", ".csv", ".json", ".tex", ".r", ".R"):
        return []
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        txt = raw.decode("utf-8", errors="ignore")
    except Exception:
        return []
    return LOCALPATH_PAT.findall(txt)


def is_mojibake(name):
    """判断文件名是否乱码（典型：UTF-8 被按 GBK 解码后的产物）"""
    bad_chars = set("µ¡Ñڬñ鍐呭锟斤拷ÃÂåæçèéêëìíîïðñòóôõö")
    hits = sum(1 for c in name if c in bad_chars or "\u0080" <= c <= "\u00ff")
    # 中文正常不算乱码
    cjk = sum(1 for c in name if "\u4e00" <= c <= "\u9fff")
    if cjk:
        return False
    return hits >= 2


def check_image(path):
    try:
        from PIL import Image
        im = Image.open(path)
        info = {"size": im.size, "mode": im.mode, "dpi": im.info.get("dpi", (0, 0))}
        return info
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--whitelist", default=None)
    ap.add_argument("--init-whitelist", action="store_true")
    ap.add_argument("--out", default="package_report.md")
    a = ap.parse_args()

    if not os.path.isdir(a.package):
        print(f"目录不存在: {a.package}"); sys.exit(2)

    files = []
    for root, _, fs in os.walk(a.package):
        for f in fs:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, a.package)
            files.append((rel, full))
    files.sort()

    print(f"包内 {len(files)} 个文件\n")

    # ---- 初始化白名单 ----
    if a.init_whitelist:
        wl_path = os.path.join(a.package, "_whitelist.txt")
        with open(wl_path, "w", encoding="utf-8") as f:
            for rel, _ in files:
                f.write(rel + "\n")
        print(f"已生成白名单 {wl_path}（{len(files)} 条）")
        print("检查它，删掉不该存在的，然后用 --whitelist 跑正式检查")
        return

    # ---- 白名单比对 ----
    if a.whitelist and os.path.exists(a.whitelist):
        allowed = {l.strip().replace("/", os.sep) for l in open(a.whitelist, encoding="utf-8") if l.strip()}
        actual = {rel for rel, _ in files}
        extra = actual - allowed
        missing = allowed - actual
        add("ok" if not extra else "fail", "白名单外文件",
            "" if not extra else f"{len(extra)} 个: {sorted(extra)[:5]}")
        add("ok" if not missing else "warn", "白名单内缺失",
            "" if not missing else f"{len(missing)} 个: {sorted(missing)[:5]}")

    # ---- 逐文件 ----
    for rel, full in files:
        name = os.path.basename(rel)

        # 内部文件
        if INTERNAL_PAT.search(name):
            add("fail", f"疑似内部文件: {rel}", "不应出现在投稿包")

        # 乱码文件名
        if is_mojibake(name):
            add("fail", f"文件名乱码: {rel}", "双重编码损坏")

        # 隐藏/系统文件
        if name.startswith(".") or name.startswith("~$") or name == "Thumbs.db":
            add("fail", f"系统文件: {rel}", "不应打包")

        # 本机路径
        lp = scan_content_for_localpaths(full)
        if lp:
            add("fail", f"含本机路径: {rel}", f"{len(lp)} 处，如 `{lp[0]}`")

        # BOM
        if name.lower().endswith(".csv"):
            with open(full, "rb") as f:
                if f.read(3) == b"\xef\xbb\xbf":
                    add("fail", f"CSV 含 BOM: {rel}", "跨软件读取会污染列名")

        # 图片
        ext = os.path.splitext(name)[1].lower()
        if ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
            info = check_image(full)
            if "error" in info:
                add("fail", f"图无法打开: {rel}", info["error"])
            else:
                dpi = float(info["dpi"][0]) if info.get("dpi") else 0.0
                if dpi and dpi < 300:
                    add("fail", f"图分辨率不足: {rel}", f"{dpi:.0f} dpi")
                else:
                    msg = f"{info['size'][0]}×{info['size'][1]}, {info['mode']}"
                    if dpi:
                        msg += f", {dpi:.0f} dpi"
                    add("ok", f"图 {rel}", msg)

        # docx 可读
        if name.lower().endswith(".docx"):
            try:
                from docx import Document
                d = Document(full)
                n_p = len([p for p in d.paragraphs if p.text.strip()])
                add("ok" if n_p > 10 else "warn", f"docx {rel}", f"{n_p} 个非空段落")
            except Exception as e:
                add("fail", f"docx 无法读取: {rel}", str(e))

        # 空文件
        if os.path.getsize(full) == 0:
            add("fail", f"空文件: {rel}", "0 字节")

    # ---- 汇总 ----
    n_fail = sum(1 for r in R if r["level"] == "fail")
    n_warn = sum(1 for r in R if r["level"] == "warn")
    n_ok = sum(1 for r in R if r["level"] == "ok")

    lines = ["# 投稿包检查报告\n",
             f"共 {len(files)} 个文件：{n_ok} 通过 ｜ {n_fail} 阻断 ｜ {n_warn} 警告\n"]
    if n_fail:
        lines.append("> ⛔ 有阻断项，**不得提交**。\n")
    for r in R:
        mark = {"ok": "✓", "fail": "✗", "warn": "⚠"}[r["level"]]
        lines.append(f"- {mark} **{r['label']}**" + (f" — {r['detail']}" if r["detail"] else ""))

    out = "\n".join(lines)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print(f"\n报告写入 {a.out}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
