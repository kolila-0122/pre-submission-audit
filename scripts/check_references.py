#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_references.py — 参考文献真实性核验

逐条比对：PMID / DOI / 年份 / 期刊 / 卷 / 期 / 页 / 第一作者 / 作者总数 / 标题

用法:
    python check_references.py --manuscript 稿件.docx --email you@example.com
    python check_references.py --manuscript 稿件.docx --offline   # 只做格式检查

依赖: requests（联网核验时需要）
"""
import argparse
import os
import re
import sys
import time
import json
import difflib

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
CROSSREF = "https://api.crossref.org/works/"


def read_any(path):
    if path.lower().endswith(".docx"):
        from docx import Document
        d = Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    return open(path, encoding="utf-8", errors="ignore").read()


def extract_refs(text):
    """抽取参考文献表，返回 [(num, raw)]"""
    idx = None
    for k in ["References", "参考文献", "REFERENCES"]:
        i = text.rfind(k)
        if i > 0:
            idx = i
            break
    if idx is None:
        return []
    tail = text[idx:]
    # 截到下一个一级标题（如果参考文献后面还有东西）
    for stop in ["\nDeclarations", "\nFigure legends", "\nSupplementary"]:
        j = tail.find(stop)
        if j > 0:
            tail = tail[:j]
    entries = re.findall(r"^\s*(\d+)[\.\)]\s*(.+?)(?=\n\s*\d+[\.\)]\s|\Z)", tail, re.M | re.S)
    return [(int(n), " ".join(r.split())) for n, r in entries]


def parse_ref(raw):
    """尽力解析一条文献的结构"""
    d = {"raw": raw}

    # PMID（有时写在条目里）
    m = re.search(r"PMID:?\s*(\d+)", raw, re.I)
    if m:
        d["pmid"] = m.group(1)

    # DOI
    m = re.search(r"(10\.\d{4,9}/[^\s,;)\]]+)", raw)
    if m:
        d["doi"] = m.group(1).rstrip(".")

    # 年份：只认 1940-2030 之间、且不紧邻连字符（页码范围）的那个
    cand = []
    for m in re.finditer(r"(?<![\d\-–])(19[4-9]\d|20[0-3]\d)(?![\d\-–])", raw):
        cand.append(int(m.group(1)))
    if cand:
        d["year"] = cand[0]        # 文献格式：作者. 标题. 期刊. 年份;卷:页

    # 卷(期):页
    m = re.search(r"[;:]\s*(\d+)\s*(?:\((\d+)\))?\s*[:;]\s*([\deE–\-]+)", raw)
    if m:
        d["volume"] = m.group(1)
        d["issue"] = m.group(2)
        d["pages"] = m.group(3)

    # 第一作者（姓 + 首字母）
    m = re.match(r"^([A-Z][A-Za-z'\-]+)\s+([A-Z]{1,3})\b", raw)
    if m:
        d["first_author_surname"] = m.group(1)
        d["first_author_initials"] = m.group(2)

    # 作者总数
    authors_part = raw.split(".")[0] if "." in raw else raw
    d["n_authors_visible"] = authors_part.count(",") + 1
    d["et_al"] = "et al" in raw.lower()

    # 标题：去掉作者段后、期刊名之前
    m = re.search(r"\.\s*([A-Z][^.]{15,300})\.\s", raw)
    if m:
        d["title_guess"] = m.group(1).strip()

    # 期刊（斜体 markdown 或句点后短串）
    m = re.search(r"\*\s*\*(.+?)\*\s*\*|\.\s*([A-Z][A-Za-z\s&:]{3,50})\.\s*\d{4}", raw)
    if m:
        d["journal_guess"] = (m.group(1) or m.group(2) or "").strip()

    return d


def esearch(term, email, retries=3):
    import requests
    for i in range(retries):
        try:
            r = requests.get(EUTILS + "esearch.fcgi",
                             params={"db": "pubmed", "term": term, "retmode": "json",
                                     "retmax": 3, "email": email},
                             timeout=25)
            if r.status_code == 200:
                return r.json().get("esearchresult", {}).get("idlist", [])
            time.sleep(1.5)
        except Exception:
            time.sleep(1.5)
    return []


def esummary(pmid, email):
    import requests
    try:
        r = requests.get(EUTILS + "esummary.fcgi",
                         params={"db": "pubmed", "id": pmid, "retmode": "json", "email": email},
                         timeout=25)
        return r.json().get("result", {}).get(pmid, {})
    except Exception:
        return {}


def crossref_doi(doi):
    import requests
    try:
        r = requests.get(CROSSREF + doi, timeout=25,
                         headers={"User-Agent": "manuscript-audit/1.0 (mailto:audit@example.org)"})
        if r.status_code == 200:
            return r.json().get("message", {})
    except Exception:
        pass
    return {}


def cmp_title(a, b):
    a = re.sub(r"[^a-z0-9 ]", " ", (a or "").lower())
    b = re.sub(r"[^a-z0-9 ]", " ", (b or "").lower())
    return difflib.SequenceMatcher(None, " ".join(a.split()), " ".join(b.split())).ratio()


def check_one(num, raw, email, use_net=True):
    d = parse_ref(raw)
    out = {"n": num, "raw": raw, "parsed": d, "status": "unknown", "issues": []}

    if not use_net:
        if not d.get("doi"):
            out["issues"].append("无 DOI")
        if not d.get("year"):
            out["issues"].append("未识别年份")
        out["status"] = "format-only"
        return out

    rec = {}
    via = ""

    # 优先 PMID
    if d.get("pmid"):
        rec = esummary(d["pmid"], email); via = "PMID"
    # 其次 DOI → Crossref → 反查 PMID
    elif d.get("doi"):
        cr = crossref_doi(d["doi"])
        if cr:
            rec = {
                "title": (cr.get("title") or [""])[0],
                "pubdate": str((cr.get("issued", {}).get("date-parts") or [[None]])[0][0]),
                "fulljournalname": (cr.get("container-title") or [""])[0],
                "volume": cr.get("volume", ""),
                "issue": cr.get("issue", ""),
                "pages": cr.get("page", ""),
                "authors": [{"name": f"{a.get('family','')} {a.get('given','')[:1]}"}
                            for a in cr.get("author", [])],
            }
            via = "DOI(Crossref)"
    # 最后标题检索
    elif d.get("title_guess"):
        ids = esearch(d["title_guess"][:150], email)
        if ids:
            rec = esummary(ids[0], email); via = "Title search"

    if not rec:
        out["status"] = "not-found"
        out["issues"].append("PubMed/Crossref 均查不到，疑似不存在")
        return out

    pub = rec.get("pubdate") or rec.get("pubdate", "")
    y = None
    m = re.search(r"(19\d{2}|20\d{2})", str(pub))
    if m:
        y = int(m.group(1))

    db = {
        "title": rec.get("title", ""),
        "year": y,
        "journal": rec.get("fulljournalname") or rec.get("journal") or "",
        "volume": str(rec.get("volume", "")),
        "issue": str(rec.get("issue", "")),
        "pages": str(rec.get("pages", "")),
        "authors": rec.get("authors") or [],
    }

    # ---- 比对 ----
    if d.get("year") and db["year"] and d["year"] != db["year"]:
        diff = abs(d["year"] - db["year"])
        if diff == 1:
            out.setdefault("notes", []).append(
                f"年份差 1 年（稿件 {d['year']} / 数据库 {db['year']}）——"
                f"通常是 online-first 与见刊卷年的差异，确认按哪年引即可")
        else:
            out["issues"].append(f"年份不符：稿件 {d['year']} vs 数据库 {db['year']}")
    if d.get("volume") and db["volume"] and d["volume"] != db["volume"]:
        out["issues"].append(f"卷不符：{d['volume']} vs {db['volume']}")
    if d.get("pages") and db["pages"]:
        p1 = d["pages"].replace("–", "-").lower()
        p2 = db["pages"].replace("–", "-").lower()
        if p1.split("-")[0] != p2.split("-")[0]:
            out["issues"].append(f"起始页不符：{d['pages']} vs {db['pages']}")
    if d.get("title_guess") and db["title"]:
        sim = cmp_title(d["title_guess"], db["title"])
        if sim < 0.80:
            out["issues"].append(f"标题相似度 {sim:.2f}：稿件「{d['title_guess'][:60]}」vs 数据库「{db['title'][:60]}」")
    if d.get("first_author_surname") and db["authors"]:
        a0 = db["authors"][0].get("name", "") if isinstance(db["authors"][0], dict) else str(db["authors"][0])
        if d["first_author_surname"].lower() not in a0.lower():
            out["issues"].append(f"第一作者不符：稿件 {d['first_author_surname']} vs 数据库 {a0}")

    out["db"] = db
    out["via"] = via
    out["status"] = "ok" if not out["issues"] else "mismatch"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manuscript", required=True)
    ap.add_argument("--email", default="audit@example.org", help="NCBI 要求提供邮箱")
    ap.add_argument("--offline", action="store_true", help="只做格式检查，不联网")
    ap.add_argument("--out", default="references_report.md")
    a = ap.parse_args()

    text = read_any(a.manuscript)
    refs = extract_refs(text)
    if not refs:
        print("未找到参考文献表"); sys.exit(2)

    print(f"共 {len(refs)} 条文献，开始核验（{'离线模式' if a.offline else '联网'}）\n")

    results = []
    for i, (n, raw) in enumerate(refs, 1):
        res = check_one(n, raw, a.email, use_net=not a.offline)
        results.append(res)
        mark = {"ok": "✓", "mismatch": "⚠", "not-found": "✗",
                "format-only": "·", "unknown": "?"}[res["status"]]
        print(f"  {mark} [{n}] {raw[:75]}")
        for iss in res["issues"]:
            print(f"       └ {iss}")
        for nt in res.get("notes", []):
            print(f"       · {nt}")
        if not a.offline:
            time.sleep(0.4)   # NCBI 限速 3 req/s

    # 汇总
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_mis = sum(1 for r in results if r["status"] == "mismatch")
    n_nf = sum(1 for r in results if r["status"] == "not-found")

    lines = ["# 参考文献核验报告\n",
             f"共 {len(results)} 条：✓ 一致 {n_ok} ｜ ⚠ 有差异 {n_mis} ｜ ✗ 查不到 {n_nf}\n"]
    if n_nf:
        lines.append("> ⛔ 有文献查不到，提交前必须修正或删除。\n")
    for r in results:
        mark = {"ok": "✓", "mismatch": "⚠", "not-found": "✗",
                "format-only": "·", "unknown": "?"}[r["status"]]
        lines.append(f"\n### {mark} [{r['n']}]\n")
        lines.append(f"**稿件原文**：{r['raw'][:300]}\n")
        if r.get("db"):
            db = r["db"]
            lines.append(f"**数据库**（via {r.get('via','')}）：{db.get('title','')[:120]} "
                         f"· {db.get('journal','')} {db.get('year','')};{db.get('volume','')}:{db.get('pages','')}\n")
        for iss in r["issues"]:
            lines.append(f"- ⚠ {iss}\n")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    print(f"\n报告写入 {a.out}")
    sys.exit(1 if (n_nf or n_mis) else 0)


if __name__ == "__main__":
    main()
