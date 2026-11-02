#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
audit_manuscript.py — 六维度稿件终检

用法:
    python audit_manuscript.py --manuscript 稿件.docx --tables 表格目录 \
        --figures 图目录 --data-scripts 脚本目录 --out report.md
"""
import argparse
import os
import re
import sys
import glob
import json
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# ---------- 结果收集 ----------
R = []   # (level, dim, label, detail)
def add(level, dim, label, detail=""):
    R.append({"level": level, "dim": dim, "label": label, "detail": detail})

# ---------- 读取稿件 ----------
def read_docx(path):
    try:
        from docx import Document
        d = Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(c.text for c in row.cells))
        return "\n".join(parts)
    except Exception as e:
        print(f"[警告] docx 读取失败: {e}")
        return ""

def read_any(path):
    """支持 docx / md / txt"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx(path)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()

def split_sections(text):
    """按 markdown 或 Word 式标题切节"""
    secs = {}
    # markdown
    if re.search(r"^#{1,3}\s+\S", text, re.M):
        cur = "_front"
        buf = []
        for ln in text.split("\n"):
            m = re.match(r"^#{1,3}\s+(.+)$", ln)
            if m:
                secs[cur] = "\n".join(buf)
                cur = m.group(1).strip()
                buf = []
            else:
                buf.append(ln)
        secs[cur] = "\n".join(buf)
        return secs
    # Word 平铺：用常见章节名切
    names = ["Abstract", "摘要", "Introduction", "引言", "Background", "Methods",
             "方法", "Materials and Methods", "Results", "结果", "Discussion",
             "讨论", "Conclusions", "结论", "References", "参考文献",
             "Declarations", "Figure legends", "图注"]
    pat = r"^(?:" + "|".join(re.escape(n) for n in names) + r")\s*$"
    cur = "_front"; buf = []
    for ln in text.split("\n"):
        if re.match(pat, ln.strip()):
            secs[cur] = "\n".join(buf)
            cur = ln.strip(); buf = []
        else:
            buf.append(ln)
    secs[cur] = "\n".join(buf)
    return secs

def wc(t):
    """英文词数：字母数字开头、允许连字符"""
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", t))

# ================= D1 结构 =================
def d1_structure(text, secs):
    dim = "D1 结构"
    w = wc(text)
    add("info", dim, "总词数", str(w))

    need = ["Abstract", "Introduction", "Methods", "Results", "Discussion", "References"]
    zh_map = {"Abstract": ["Abstract", "摘要"], "Introduction": ["Introduction", "引言", "Background"],
              "Methods": ["Methods", "方法", "Materials and Methods"],
              "Results": ["Results", "结果"], "Discussion": ["Discussion", "讨论"],
              "References": ["References", "参考文献"]}
    for k, cands in zh_map.items():
        found = any(c in secs for c in cands)
        add("ok" if found else "fail", dim, f"章节 {k}", "存在" if found else "缺失")

    # 摘要长度
    for c in ["Abstract", "摘要"]:
        if c in secs:
            n = wc(secs[c])
            add("ok" if 150 <= n <= 350 else "warn", dim, f"摘要长度 {n} 词",
                "正常范围" if 150 <= n <= 350 else "偏离常见范围 150-350")
            break

    # 关键词
    add("ok" if re.search(r"keywords?|关键词", text, re.I) else "warn", dim, "关键词",
        "存在" if re.search(r"keywords?|关键词", text, re.I) else "未找到")

    # 声明
    DECL = {
        "Competing interests": r"competing interests|conflict of interest|利益冲突",
        "Funding": r"\bfunding\b|基金|资助",
        "Data availability": r"availability of data|data availability|数据可用",
        "Ethics": r"\bethics?\b|ethical approval|伦理",
        "Authors' contributions": r"authors?.{0,3}contributions?|作者贡献",
    }
    for label, pat in DECL.items():
        add("ok" if re.search(pat, text, re.I) else "warn", dim, f"声明 {label}",
            "存在" if re.search(pat, text, re.I) else "未找到")

# ================= D2 数据一致性 =================
def d2_data(text, tables_dir):
    dim = "D2 数据一致性"
    if not tables_dir or not os.path.isdir(tables_dir):
        add("warn", dim, "无表格目录", "跳过")
        return
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        add("warn", dim, "pandas 未安装", "跳过")
        return

    # 抽取正文中的数字（带千分位）
    nums_text = set()
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{2,}\b", text):
        nums_text.add(int(m.group(0).replace(",", "")))
    small = set()
    for m in re.finditer(r"(?<![\d.])\d{1,2}(?![\d.])", text):
        small.add(int(m.group(0)))

    for f in sorted(glob.glob(os.path.join(tables_dir, "*.csv"))):
        name = os.path.basename(f)
        try:
            T = pd.read_csv(f, comment="#")
        except Exception:
            continue
        # 数值列求和（只对计数类列，不对 p 值/相关系数/百分比求和）
        def is_count_col(col):
            cl = str(col).lower()
            # 只对"可加总的计数"求和：精确匹配 n / events / responders，
            # 排除 "n cell lines"（每行重复计数）等
            if cl.strip() in ("n", "events", "event", "count", "responders", "total", "n_patients"):
                return True
            return False
        for c in T.columns:
            if not pd.api.types.is_numeric_dtype(T[c]) or not is_count_col(c):
                continue
            s = int(round(T[c].sum()))
            if s > 30 and s not in nums_text:
                add("warn", dim, f"{name} 列 {c} 合计 {s}", "正文未出现该合计值（确认是否需要报告）")
        # p 值截断检查（只认真正的 p/FDR 列）
        def is_pcol(col):
            cl = str(col).lower().replace(" ", "")
            if any(x in cl for x in ["rho", "rank", "attenuation", "i2", "n("]):
                return False
            return cl in ("p", "pvalue", "pval", "padj", "fdr", "qvalue") \
                or cl.startswith("p(") or cl.startswith("p_") or "p(sci)" in cl \
                or cl.startswith("fdr") or cl.endswith("_p") or cl.endswith("(p)")
        for c in T.columns:
            if not is_pcol(c):
                continue
            cs = T[c].astype(str)
            n_zero = int((cs == "0.0").sum())
            if n_zero:
                add("fail", dim, f"{name} 列 {c}", f"{n_zero} 个值写作 0.0（p 值不得为 0）")
            n_cens = int((cs.str.contains("<1e-300")).sum())
            if n_cens:
                add("warn", dim, f"{name} 列 {c}", f"{n_cens} 个 <1e-300，需确认真实值")
        # BOM
        with open(f, "rb") as fh:
            if fh.read(3) == b"\xef\xbb\xbf":
                add("fail", dim, f"{name}", "含 UTF-8 BOM")

    # 量纲一致性：同一概念在不同表里数量级差太多
    for f in sorted(glob.glob(os.path.join(tables_dir, "*.csv"))):
        try:
            T = pd.read_csv(f, comment="#")
        except Exception:
            continue
        for c in T.columns:
            if not pd.api.types.is_numeric_dtype(T[c]):
                continue
            cl = str(c).lower()
            if any(x in cl for x in ["p (", "p(", "fdr", "qvalue", "rho", "rank"]):
                continue          # p 值天然跨数量级，不是量纲问题
            v = T[c].dropna()
            if len(v) < 3:
                continue
            pos = v[v > 0]
            if len(pos) < 3:
                continue
            ratio = pos.max() / max(pos.min(), 1e-12)
            if ratio > 1e4:
                add("warn", dim, f"{os.path.basename(f)} 列 {c}",
                    f"极值比 {ratio:.0e}，疑似量纲混杂（log 变换/单位不一致）")

# ================= D3 图像一致性 =================
def d3_figures(text, secs, fig_dir):
    dim = "D3 图像一致性"
    body_end = text.find("References")
    body = text[:body_end] if body_end > 0 else text
    leg_key = None
    for k in secs:
        if "legend" in k.lower() or "图注" in k:
            leg_key = k
    legends = secs.get(leg_key, "")

    # 图注里的图号
    leg_figs = re.findall(r"(?:Figure|Fig\.?|图)\s*(S?\d+)", legends)
    leg_set = sorted(set(leg_figs), key=lambda x: (x.startswith("S"), x))

    # 正文引用（严格匹配，避免 Figure 1 吃掉 Figure S1）
    cite = {}
    for f in leg_set:
        pat = (r"Figure\s*" + re.escape(f) + r"(?![\d])") if not f.startswith("S") \
              else (r"Figure\s*" + re.escape(f) + r"(?![\d])")
        cite[f] = len(re.findall(pat, body))

    add("info", dim, "图注图号", str(leg_set))
    for f, n in cite.items():
        add("ok" if n > 0 else "fail", dim, f"Figure {f} 正文引用", f"{n} 次")

    # 图文件
    if fig_dir and os.path.isdir(fig_dir):
        files = [f for f in os.listdir(fig_dir)
                 if os.path.splitext(f)[1].lower() in (".pdf", ".tif", ".tiff", ".png", ".eps", ".jpg")]
        add("ok" if len(files) == len(leg_set) else "warn", dim,
            f"图文件 {len(files)} 个 vs 图注 {len(leg_set)} 条",
            "" if len(files) == len(leg_set) else "数量不匹配")
        # CMYK 检查
        try:
            from PIL import Image
            for f in files:
                if f.lower().endswith(".tif"):
                    im = Image.open(os.path.join(fig_dir, f))
                    add("ok" if im.mode == "CMYK" else "warn", dim,
                        f"{f} 色彩模式", im.mode)
        except Exception:
            pass
        # 分辨率
        try:
            from PIL import Image
            for f in files:
                if f.lower().endswith((".tif", ".png")):
                    im = Image.open(os.path.join(fig_dir, f))
                    dpi = im.info.get("dpi", (0, 0))[0]
                    if dpi and dpi < 300:
                        add("fail", dim, f"{f} 分辨率", f"{dpi:.0f} dpi < 300")
        except Exception:
            pass
    else:
        add("warn", dim, "无图目录", "跳过文件核对（图注描述 vs 图面仍需人工看图）")

    add("warn", dim, "图注内容 vs 图面实际", "★必须人工打开图核对★（如'标了五个化合物'→数一遍）")

# ================= D4 参考文献 =================
def d4_refs(text, secs):
    dim = "D4 参考文献"
    ref_key = None
    for k in secs:
        if k.lower() in ("references", "参考文献"):
            ref_key = k
    if not ref_key:
        add("fail", dim, "参考文献章节", "未找到")
        return
    refs = secs[ref_key]

    # 条目
    entries = re.findall(r"^\s*(\d+)[\.\)]\s*(.+)$", refs, re.M)
    add("info", dim, "文献条数", str(len(entries)))
    listed = [int(n) for n, _ in entries]
    add("ok" if listed == sorted(listed) else "fail", dim,
        "文献编号递增", "" if listed == sorted(listed) else f"实际 {listed[:10]}...")

    # 正文引用
    body = text[:text.find(ref_key)] if ref_key in text else text
    cited = []
    for m in re.finditer(r"\[([\d,\s–\-]+)\]", body):
        for x in re.split(r"[,–\-]", m.group(1)):
            x = x.strip()
            if x.isdigit():
                cited.append(int(x))
    cited_set = set(cited)
    lst = set(listed)
    add("ok" if not (cited_set - lst) else "fail", dim, "引用未列出",
        str(sorted(cited_set - lst)))
    add("ok" if not (lst - cited_set) else "fail", dim, "列出未引用",
        str(sorted(lst - cited_set)))

    # 首次出现顺序（Vancouver）
    first_order = []
    seen = set()
    for m in re.finditer(r"\[([\d,\s–\-]+)\]", body):
        for x in re.split(r"[,–\-]", m.group(1)):
            x = x.strip()
            if x.isdigit():
                v = int(x)
                if v not in seen:
                    seen.add(v); first_order.append(v)
    add("ok" if first_order == list(range(1, len(first_order) + 1)) else "warn", dim,
        "首现顺序 = 编号顺序（Vancouver）",
        "" if first_order == list(range(1, len(first_order) + 1)) else f"前 10 位: {first_order[:10]}")

    # 年份合理性
    years = []
    for _, e in entries:
        for y in re.findall(r"\b(19|20)\d{2}\b", e):
            pass
        m = re.search(r"\b(19\d{2}|20\d{2})\b", e)
        if m:
            years.append(int(m.group(1)))
    if years:
        add("ok" if max(years) <= 2026 else "fail", dim, "最晚年份", str(max(years)))
        add("warn" if min(years) < 1950 else "ok", dim, "最早年份", str(min(years)))

    # DOI 格式
    dois = re.findall(r"10\.\d{4,9}/[^\s,;)\]]+", refs)
    add("info", dim, "DOI 数量", f"{len(dois)} / {len(entries)} 条")
    if dois:
        bad = [d for d in dois if not re.match(r"10\.\d{4,9}/\S+", d)]
        add("ok" if not bad else "fail", dim, "DOI 格式", str(bad[:3]))

    add("warn", dim, "文献真实性（PMID/DOI/年份/卷页/作者序）",
        "★必须跑 check_references.py 联网核验★")

# ================= D5 写作质量 =================
def d5_writing(text, secs):
    dim = "D5 写作质量"

    # 假大空
    empty = [r"\bnovel\b", r"\bgroundbreaking\b", r"for the first time",
             r"\bimportantly\b", r"\bnotably\b", r"crucial role",
             r"opens? new avenues?", r"sheds? light on",
             r"重大意义", r"首次揭示", r"提供了?新思路", r"fill the gap"]
    hits = []
    for p in empty:
        for m in re.finditer(p, text, re.I):
            s = max(0, m.start() - 40)
            hits.append(text[s:m.end() + 40].replace("\n", " "))
    add("warn" if hits else "ok", dim, f"假大空表述 {len(hits)} 处",
        "；".join(h[:80] for h in hits[:3]))

    # 防御型写作
    defensive = [r"it should be noted", r"it is worth mentioning", r"to the best of our knowledge",
                 r"\barguably\b", r"\bpresumably\b", r"may potentially", r"might possibly",
                 r"could be interpreted as", r"严格来说", r"需要指出的是", r"不可否认",
                 r"在一定程度上", r"有望"]
    hits2 = []
    for p in defensive:
        for m in re.finditer(p, text, re.I):
            s = max(0, m.start() - 40)
            hits2.append(text[s:m.end() + 40].replace("\n", " "))
    add("warn" if hits2 else "ok", dim, f"防御型句式 {len(hits2)} 处",
        "；".join(h[:80] for h in hits2[:3]))

    # 句长
    sents = re.split(r"(?<=[.!?。！？])\s+", text)
    long_s = [s for s in sents if wc(s) > 45]
    add("warn" if long_s else "ok", dim, f"超长句（>45 词）{len(long_s)} 处",
        "；".join(s[:70] for s in long_s[:2]))

    # 被动语态密度
    passive = len(re.findall(r"\b(?:is|are|was|were|be|been|being)\s+\w+ed\b", text))
    total = max(wc(text), 1)
    ratio = passive / total * 100
    add("ok" if ratio < 3 else "warn", dim, f"被动语态密度 {ratio:.1f}%",
        "正常" if ratio < 3 else "偏高，建议改主动")

    # 同义重复（同一 8 词片段出现 ≥3 次）
    words = re.findall(r"[a-z]{4,}", text.lower())
    grams = [" ".join(words[i:i + 6]) for i in range(len(words) - 5)]
    cnt = Counter(grams)
    rep = [(g, c) for g, c in cnt.most_common(30) if c >= 3]
    add("warn" if rep else "ok", dim, f"重复 6-gram {len(rep)} 组",
        "；".join(f"'{g}'×{c}" for g, c in rep[:3]))

    # 破折号密度
    em = text.count("—")
    en = text.count("–")
    per1k = (em + en) / max(wc(text), 1) * 1000
    add("ok" if per1k < 3 else "warn", dim, f"破折号密度 {per1k:.1f}/千词",
        f"em={em} en={en}" + ("（偏高，常见为 1-2）" if per1k >= 3 else ""))

# ================= D6 假设与主张 =================
def d6_hypothesis(text, secs):
    dim = "D6 假设与主张"
    # 标题
    title = ""
    for k in secs:
        if k.lower() in ("_front", "title", ""):
            title = secs[k].strip().split("\n")[0]
            break
    if not title:
        first = [ln for ln in text.split("\n") if ln.strip()][:1]
        title = first[0] if first else ""
    add("info", dim, "标题", title[:120])

    # 强主张词 vs 效应量
    strong = [r"\bstrongly\b", r"\brobust\b", r"\bdefinitive\b", r"\bproves?\b",
              r"\bdemonstrates?\b", r"\bestablishes?\b", r"independently prognostic",
              r"重大", r"证明", r"确证"]
    hits = [p for p in strong if re.search(p, title, re.I)]
    if hits:
        add("warn", dim, "标题含强主张词", f"{hits} → 核对效应量是否撑得起")

    # 提取 HR / AUC / p 的量级
    hrs = [float(x) for x in re.findall(r"HR\s*=?\s*([0-9]+\.[0-9]+)", text)]
    aucs = [float(x) for x in re.findall(r"AUC\s*=?\s*([01]\.[0-9]+)", text)]
    if hrs:
        mx = max(hrs); mn = min(hrs)
        add("info", dim, "HR 范围", f"{mn:.2f}–{mx:.2f}")
        if mx < 1.1 and re.search(r"independently prognostic|strong", title, re.I):
            add("fail", dim, "效应量 vs 标题主张",
                f"HR 最大仅 {mx:.3f}，但标题声称 independently prognostic")
        elif mx < 1.5:
            add("warn", dim, "效应量偏小", f"HR {mn:.2f}–{mx:.2f}，措辞应含 'weakly/small'")
    if aucs:
        add("info", dim, "AUC 范围", f"{min(aucs):.2f}–{max(aucs):.2f}")
        if max(aucs) < 0.55 and re.search(r"predict|biomarker", title, re.I):
            add("fail", dim, "效应量 vs 标题主张",
                f"AUC 最大 {max(aucs):.2f}，不足以称 predictor")

    # 阴性结果是否淡化
    for pat, label in [(r"ran opposite", "用 'ran opposite' 描述显著反向结果"),
                       (r"did not reach significance", "未给具体 p 值"),
                       (r"trend toward", "'trend toward' 掩盖不显著")]:
        if re.search(pat, text, re.I):
            add("warn", dim, label, "检查是否给出了具体统计量")

    # 单队列显著性
    add("warn", dim, "单队列 vs 合并结果", "★核对：合并显著而单队列全不显著时，须明说★")

# ================= 输出 =================
def write_report(path):
    lv = {"fail": "✗", "warn": "⚠", "ok": "✓", "info": "·"}
    lines = ["# 稿件终检报告\n"]
    n_fail = sum(1 for r in R if r["level"] == "fail")
    n_warn = sum(1 for r in R if r["level"] == "warn")
    n_ok = sum(1 for r in R if r["level"] == "ok")
    lines.append(f"**结论：{n_fail} 个阻断项，{n_warn} 项需人工确认，{n_ok} 项通过**\n")
    if n_fail:
        lines.append("> ⛔ 存在阻断项，**不得提交**。\n")

    dims = []
    for r in R:
        if r["dim"] not in dims:
            dims.append(r["dim"])
    for d in dims:
        lines.append(f"\n## {d}\n")
        for r in [x for x in R if x["dim"] == d]:
            mark = lv[r["level"]]
            if r["detail"]:
                lines.append(f"- {mark} **{r['label']}** — {r['detail']}")
            else:
                lines.append(f"- {mark} {r['label']}")
    out = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    return n_fail

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--tables", default=None)
    ap.add_argument("--figures", default=None)
    ap.add_argument("--data-scripts", default=None)
    ap.add_argument("--out", default="audit_report.md")
    a = ap.parse_args()

    if not os.path.exists(a.manuscript):
        print(f"找不到稿件: {a.manuscript}"); sys.exit(2)

    text = read_any(a.manuscript)
    secs = split_sections(text)

    print(f"读取 {a.manuscript}: {wc(text)} 词，{len(secs)} 节\n")

    d1_structure(text, secs)
    d2_data(text, a.tables)
    d3_figures(text, secs, a.figures)
    d4_refs(text, secs)
    d5_writing(text, secs)
    d6_hypothesis(text, secs)

    nf = write_report(a.out)
    print(f"\n报告已写入 {a.out}")
    sys.exit(1 if nf else 0)

if __name__ == "__main__":
    main()
