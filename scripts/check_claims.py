#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_claims.py — 把回复信里的每一条"已修复"映射回文件，验真假

用法:
    python check_claims.py --response Response.md --manuscript 稿件.md \
        --tables 表格目录 --package 包目录 --out claims_report.md

原理：扫描回复信中所有含 Fixed / Added / Revised / Replaced / Removed / 已修复 的行，
      提取其中的数值、文件名、声明类型，然后逐条到文件里验证。
"""
import argparse
import os
import re
import sys
import glob

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

R = []
def add(level, claim, check, detail=""):
    R.append({"level": level, "claim": claim, "check": check, "detail": detail})


def read_any(path):
    if not path or not os.path.exists(path):
        return ""
    if path.lower().endswith(".docx"):
        from docx import Document
        d = Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    return open(path, encoding="utf-8", errors="ignore").read()


def find_claim_lines(text):
    """抽取回复信中的声明句：支持普通段落 + markdown 表格行"""
    verbs = r"(?:[Ff]ixed|[Aa]dded|[Rr]evised|[Rr]eplaced|[Rr]emoved|[Rr]ewrote|[Rr]ebuilt|[Uu]pdated|" \
            r"[Dd]eleted|[Cc]orrected|[Ee]xpanded|[Rr]educed|已修复|已修改|已添加|已删除|已替换|已重建|已更正)"
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s or len(s) < 8:
            continue
        # markdown 表格行：拆单元格，保留含"已修复"类的
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            joined = " — ".join(c for c in cells if c and not set(c) <= {"-", ":"})
            if re.search(verbs, joined):
                out.append(joined)
            continue
        if re.search(verbs, s):
            out.append(s)
    return out


def collect_file_text(manuscript, tables_dir, package_dir):
    """把稿件 + 所有表格 + 包内 md 合并成一个大字符串，用于检索"""
    blob = read_any(manuscript)
    if tables_dir and os.path.isdir(tables_dir):
        for f in glob.glob(os.path.join(tables_dir, "*")):
            if f.lower().endswith((".csv", ".tsv", ".txt")):
                try:
                    blob += "\n" + open(f, encoding="utf-8", errors="ignore").read()
                except Exception:
                    pass
    if package_dir and os.path.isdir(package_dir):
        for f in glob.glob(os.path.join(package_dir, "*.md")):
            blob += "\n" + read_any(f)
    return blob


def check_numeric_claims(line, blob):
    """声明里出现的数字/数值，是否在文件中真实存在（或如实已删除）"""
    # 形如 "828 → 823" 或 "from 10 to 14" 或 "0.476 → 0.496"
    pairs = re.findall(r"([\d.,]+)\s*(?:→|->|to)\s*([\d.,]+)", line)
    for old, new in pairs:
        old_v = old.replace(",", ""); new_v = new.replace(",", "")
        if new_v and new_v not in blob.replace(",", ""):
            add("fail", line[:70], f"新值 {new} 未在文件中出现", "")
        else:
            add("ok", line[:70], f"新值 {new} 存在", "")

    # 形如 "deleted X" / "removed X"
    if re.search(r"(?:[Rr]emoved|[Dd]eleted|[Ee]liminated|已删除|已移除)", line):
        m = re.findall(r"[\"“']([^\"”']{3,40})[\"”']", line)
        for q in m:
            if q in blob:
                add("fail", line[:70], f"声称已删除的 `{q}` 仍存在于文件", "")
            else:
                add("ok", line[:70], f"`{q}` 确已不在文件中", "")

    # 形如 "N occurrences" / "0 rows"
    m = re.search(r"(?:0|zero)\s*(?:occurrences?|rows?|hits?|处)", line, re.I)
    if m:
        add("warn", line[:70], "声称 0 处，需脚本复核", "请用 audit_manuscript.py 确认")


def check_structural_claims(line, blob):
    """结构性声明：某内容是否真的在文件里"""
    kw_map = {
        "reference": r"^\s*\d+[\.\)]\s",
        "subsection": r"^#{2,3}\s",
        "subsection(md)": r"^###\s",
        "table": r"[Tt]able\s*S?\d",
        "figure": r"[Ff]igure\s*S?\d",
    }
    low = line.lower()
    if "reference" in low or "文献" in line:
        n_refs = len(re.findall(r"^\s*\d+[\.\)]\s", blob, re.M))
        m = re.search(r"(\d+)\s*(?:references|条文献|参考文献)", line)
        if m:
            claimed = int(m.group(1))
            add("ok" if claimed == n_refs else "fail", line[:70],
                f"声称 {claimed} 条，实际 {n_refs} 条", "")

    if re.search(r"(?:added|revised|新增).{0,20}(?:section|subsection|paragraph|小节|段落)", low) or \
       re.search(r"新增.{0,10}(?:小节|段落)", line):
        m = re.findall(r"[\"“']([^\"”']{5,60})[\"”']", line)
        for q in m:
            present = q.lower() in blob.lower()
            add("ok" if present else "fail", line[:70],
                f"声称新增的小节/段落 `{q[:40]}` {'存在' if present else '未找到'}", "")

    # "no longer contains" / "不再包含"
    if re.search(r"no longer|不再", line, re.I):
        m = re.findall(r"[\"“']([^\"”']{3,40})[\"”']", line)
        for q in m:
            gone = q not in blob
            add("ok" if gone else "fail", line[:70],
                f"声称已移除的 `{q}` {'确已不在' if gone else '仍存在'}", "")


def check_consistency_claims(line, blob):
    """一致性声明：如 'X is now stated in both A and B'"""
    if re.search(r"(?:both|两处|统一|consistent|一致)", line, re.I):
        m = re.findall(r"[\"“']([^\"”']{3,40})[\"”']", line)
        for q in m:
            n = blob.count(q)
            add("ok" if n >= 2 else "warn", line[:70],
                f"声称一致的 `{q[:30]}` 出现 {n} 次",
                "" if n >= 2 else "只在 1 处出现，可能未统一")

    # "in the Methods" / "在方法中"
    if re.search(r"(?:Methods|方法)", line):
        in_methods = bool(re.search(r"##\s*Methods.{0,20000}?" + re.escape(
            (re.findall(r"[\"“']([^\"”']{5,40})[\"”']", line) or [""])[0]), blob, re.S))
        q = (re.findall(r"[\"“']([^\"”']{5,40})[\"”']", line) or [None])[0]
        if q:
            add("ok" if q in blob else "fail", line[:70],
                f"声称写入 Methods 的 `{q[:40]}` {'存在' if q in blob else '未找到'}", "")


def check_package_claims(line, package_dir):
    """包内文件声明"""
    if not package_dir or not os.path.isdir(package_dir):
        return
    m = re.search(r"(\d+)\s*(?:files?|个文件)", line)
    if m:
        claimed = int(m.group(1))
        actual = sum(len(f) for _, _, f in os.walk(package_dir))
        add("ok" if claimed == actual else "fail", line[:70],
            f"声称 {claimed} 个文件，实际 {actual} 个", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--response", required=True)
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--tables", default=None)
    ap.add_argument("--package", default=None)
    ap.add_argument("--out", default="claims_report.md")
    a = ap.parse_args()

    resp = read_any(a.response)
    blob = collect_file_text(a.manuscript, a.tables, a.package)
    claims = find_claim_lines(resp)

    print(f"从回复信提取 {len(claims)} 条声明，逐条核验\n")

    for ln in claims:
        check_numeric_claims(ln, blob)
        check_structural_claims(ln, blob)
        check_consistency_claims(ln, blob)
        check_package_claims(ln, a.package)

    n_ok = sum(1 for r in R if r["level"] == "ok")
    n_fail = sum(1 for r in R if r["level"] == "fail")
    n_warn = sum(1 for r in R if r["level"] == "warn")

    lines = ["# 声明对账报告\n",
             f"**{n_ok} 通过 ｜ {n_fail} 失败 ｜ {n_warn} 需确认**\n"]
    if n_fail:
        lines.append("> ⛔ 有声明与文件不符，**必须修正回复信或改文件**。\n")

    for r in R:
        mark = {"ok": "✓", "fail": "✗", "warn": "⚠"}[r["level"]]
        lines.append(f"\n- {mark} **{r['claim']}** → {r['check']}"
                     + (f"（{r['detail']}）" if r["detail"] else ""))

    out = "\n".join(lines)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print(f"\n报告写入 {a.out}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
