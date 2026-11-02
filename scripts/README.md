# pre-submission-audit 脚本说明

四个脚本，对应 SKILL.md 里的六个检查维度。

## 依赖

```bash
pip install python-docx pandas numpy requests pillow
```

## 1. audit_manuscript.py — 六维稿件检查

```bash
python audit_manuscript.py \
    --manuscript 稿件.docx \
    --tables 表格目录 \
    --figures 图目录 \
    --out report.md
```

**输出六节**：D1 结构 / D2 数据一致性 / D3 图像一致性 / D4 参考文献格式 / D5 写作质量 / D6 假设与主张。

三态标记：
- `✓` 通过
- `⚠` 需人工确认
- `✗` 阻断项

**退出码**：0 = 无阻断，1 = 有阻断（可接入 CI）。

### D5 会标出的写作问题

| 类型 | 关键词 |
|---|---|
| 假大空 | novel / groundbreaking / for the first time / crucial role / opens new avenues / 首次揭示 / 重大意义 |
| 防御型 | it should be noted / arguably / presumably / may potentially / 严格来说 / 在一定程度上 |
| 超长句 | > 45 词 |
| 被动语态 | 密度 > 3% |
| 重复 | 同一 6-gram 出现 ≥ 3 次 |
| 破折号 | 密度 > 3/千词 |

### D6 会标出的主张问题

- 标题含 `independently prognostic` 但 HR < 1.1 → **阻断**
- 标题含 `predict` 但 AUC < 0.55 → **阻断**
- 用 `ran opposite` / `trend toward` 描述结果 → 提示补具体统计量

---

## 2. check_references.py — 文献真实性核验

```bash
python check_references.py --manuscript 稿件.docx --email 你的邮箱
python check_references.py --manuscript 稿件.docx --offline   # 只查格式
```

**逐条比对**：PMID / DOI / 年份 / 期刊 / 卷 / 期 / 页 / 第一作者 / 标题相似度。

- 优先用条目里的 PMID 查 PubMed
- 无 PMID 但有 DOI → Crossref 反查
- 都无 → 标题检索

**年份差 1 年会作为提示而非错误**（online-first vs 见刊卷年的常见差异）。

---

## 3. check_claims.py — 声明对账

```bash
python check_claims.py \
    --response Response.md \
    --manuscript 稿件.md \
    --tables 表格目录 \
    --package 投稿包目录 \
    --out claims.md
```

扫描回复信里所有含 `Fixed / Added / Revised / Removed / 已修复` 的行，把里面的**数值、文件名、章节名**提取出来，逐条到文件里验证。

**典型输出**：
```
✓ "References expanded from 10 to 14" → 实际 14 条
✗ "Removed the sentence 'two small cohorts'" → 该串仍存在于文件
✗ "Claims 18 files" → 实际 21 个
```

**退出码 1 = 有假声明，必须修。**

---

## 4. audit_package.py — 投稿包检查

```bash
# 首次：生成当前清单作白名单，人工删掉不该有的
python audit_package.py --package 包目录 --init-whitelist

# 之后：正式检查
python audit_package.py --package 包目录 --whitelist 包目录/_whitelist.txt
```

**查**：
- 白名单外/内文件
- 内部文件残留（TODO / 笔记 / 步骤 / 含本机路径 `D:\...`）
- 乱码文件名（双重编码）
- 系统文件（`.DS_Store` / `~$xxx` / `Thumbs.db`）
- CSV 的 UTF-8 BOM
- 图分辨率 < 300 dpi、色彩模式
- docx 能否打开、空文件

---

## 推荐流程

```bash
# 1. 稿件层
python audit_manuscript.py --manuscript 稿件.docx --tables T --figures F --out r1.md

# 2. 文献层
python check_references.py --manuscript 稿件.docx --email you@x.com --out r2.md

# 3. 有回复信时
python check_claims.py --response Resp.md --manuscript 稿件.md --tables T --out r3.md

# 4. 打包后
python audit_package.py --package PKG --whitelist PKG/_whitelist.txt --out r4.md

# 5. 全部 0 阻断才提交
grep -c "✗" r1.md r2.md r3.md r4.md
```

---

## 已知限制

**脚本查不了的，必须人工做：**

1. **图注描述 vs 图面实际**——"标了五个化合物"到底标了几个，只能打开图数
2. **引用是否合理**——文献存在，但内容是否真支持你所引的主张
3. **假设是否成立**——标题的主张和结果是否匹配，需要读全文判断
4. **假大空/防御型的最终判断**——脚本只给候选句，删不删要人定
5. **数据是否编造**——脚本能查"图表是否一致"，查不了"数据是否真实存在"

这五件事，脚本只能把可疑的地方指出来，判断仍在人。
