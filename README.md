# pre-submission-audit

**A pre-submission checker for scientific manuscripts.**

Most manuscript problems that survive to peer review are not errors of analysis. They are mismatches between what the documents say and what the files contain: a p-value in the text that disagrees with the table, a figure legend that describes four panels when the image has three, a reference whose year does not match the database, a response letter that reports a correction that was never applied.

These are mechanically checkable, and almost nobody checks them mechanically.

[中文说明见下](#中文说明)

---

## What it checks

Six dimensions, four scripts.

### D1 — Structure
Section completeness, word counts, abstract length, keywords, presence of the five standard declarations (competing interests, funding, data availability, ethics, author contributions).

### D2 — Data consistency
- Table column sums vs numbers in the text
- **p-values written as `0.0`** (never acceptable; p-values must be reported in scientific notation)
- p-values censored as `<1e-300` (flags them for recomputation)
- UTF-8 BOM in CSV headers
- Order-of-magnitude anomalies within a column (a sign of mixed scales, e.g. log-transformed and raw intensities in the same table)

### D3 — Figure consistency
- Figure file count vs legend count
- Citation count for every figure in the main text (strict regex, so `Figure S1` is not counted as `Figure 1`)
- Resolution below 300 dpi, colour mode (CMYK vs RGB)
- **Flag: legend wording vs actual figure content — this one requires a human to open the image and count**

### D4 — References
- Numbering continuity, orphans in either direction (cited-but-not-listed, listed-but-not-cited)
- Vancouver first-appearance order
- DOI format
- **Truthfulness** (`check_references.py`): resolves each entry against PubMed and Crossref, comparing year, journal, volume, issue, pages, first author, author count and title similarity

### D5 — Writing quality
- **Empty phrases**: `novel`, `groundbreaking`, `for the first time`, `crucial role`, `opens new avenues`
- **Defensive writing**: `it should be noted`, `arguably`, `may potentially`, `to the best of our knowledge`
- Sentences longer than 45 words
- Passive-voice density
- Repeated 6-grams (the same idea stated several times)
- Em-dash density

### D6 — Claims and assumptions
- Strong assertions in the title matched against effect sizes:
  - `independently prognostic` with HR < 1.1 → **blocking**
  - `predicts` with AUC < 0.55 → **blocking**
- Hedging patterns that hide significant results (`ran opposite`, `trend toward`)

---

## Install

```bash
git clone https://github.com/kolila-0122/pre-submission-audit.git
cd pre-submission-audit
pip install -r requirements.txt
```

Python ≥ 3.9. No installation step beyond the dependencies.

---

## Usage

```bash
# 1. Manuscript-level audit (six dimensions)
python scripts/audit_manuscript.py \
    --manuscript manuscript.docx \
    --tables tables/ \
    --figures figures/ \
    --out report.md

# 2. Reference truthfulness (needs network)
python scripts/check_references.py \
    --manuscript manuscript.docx \
    --email you@example.org

# 3. Response-letter claim reconciliation
python scripts/check_claims.py \
    --response response.md \
    --manuscript manuscript.md \
    --tables tables/ \
    --package submission/

# 4. Submission package
python scripts/audit_package.py --package submission/ --init-whitelist   # first time
python scripts/audit_package.py --package submission/ --whitelist submission/_whitelist.txt
```

All four exit with code `1` when they find blocking issues, so they can be wired into CI.

### Interpreting the output

```
✓  passed
⚠  needs a human decision (location given)
✗  blocking — must be fixed before submission
```

**Rule: zero `✗`, and every `⚠` explicitly resolved in the report, before you upload.**

---

## Typical failure modes this catches

### 1. A legend that describes something the figure does not show

"The five compounds with the largest |ρ| are labelled" — four are labelled, and they are not the top four. The script flags legend claims that contain countable assertions; **confirming them still requires opening the image.**

### 2. p-values censored as `<1e-300`

`scipy.stats.spearmanr` returns `p = 0.0` by floating-point underflow for large n. Treating that zero as "below any representable value" produces a table that contradicts the figure beside it.

```python
# Wrong: silently returns 0.0 for large n
rho, p = stats.spearmanr(x, y)

# Right: t approximation, no underflow
t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
p = 2 * stats.t.sf(abs(t), df=n - 2)
```

### 3. Silent column-name mismatches

`if "p" in df.columns` is `False` when the column is named `p (sci)`. The recomputation block never runs, nothing is reported, and the old values stay in the file. Match loosely; print which columns were actually processed.

### 4. "The model did not converge"

Often this is a filtering bug, not a numerical one. A line that drops rows with missing covariate values will remove whole cohorts without warning. **Diagnostic: fit a single-covariate model. If it converges, the problem is the script.**

### 5. Global string replacement that rewrites the wrong sentence

Replacing `p < 1×10⁻¹⁵` with `p = 1.9×10⁻¹⁵` globally also rewrites the Methods sentence that states the *general* reporting convention, turning a specific value into a universal rule. Re-read every occurrence afterwards.

### 6. Internal files in the submission package

To-do lists, notes containing local paths (`D:\project\...`), filenames mangled by double encoding. **Build packages from an explicit whitelist, never by copying a directory.**

---

## Making a response letter machine-checkable

`check_claims.py` will reveal something uncomfortable: most response letters are unverifiable, because they say "I confirmed" instead of naming a value.

| ✗ Unverifiable | ✓ Verifiable |
|---|---|
| Fixed the reference list | References expanded from **10 to 14** |
| Corrected the p-values | Dasatinib p changed from `<1e-300` to **1.88e-15** |
| Removed the ghost cohort sentence | Removed `"two small cohorts (n = 27 each)"`; grep returns **0** |
| Updated Table S4 | `n_uni` sum = **3,291**; `ev_uni` = **823** |

Three rules:
1. **Give numbers** — before → after, both values
2. **Give strings** — put deleted or added text in backticks so it can be grepped
3. **Give the check** — `grep "xxx" → 0` where relevant

---

## What this tool cannot do

Stated plainly, because over-claiming is the failure mode this tool exists to catch.

1. **Legend vs figure content** — "five compounds labelled" needs a human to count. The script only flags it.
2. **Whether a citation supports the claim** — the script verifies that a paper exists and is cited correctly. It cannot tell whether that paper actually showed what you say it showed.
3. **Whether a hypothesis holds** — the script compares wording against effect sizes. It cannot judge whether your interpretation is right.
4. **Empty and defensive phrasing** — the script surfaces candidates; deletion is a judgement call.
5. **Fabricated data** — the script checks that figures and tables agree. It cannot check that the underlying measurements were real.

For those five, the tool points at the suspect and stops.

---

## 中文说明

**一句话**：这是一个投稿前的机器终检工具，专门查"文档里写的"和"文件里有的"对不对得上。

**六个维度**：结构 / 数据一致性 / 图像一致性 / 文献真实性 / 写作质量 / 假设与主张。

**四个脚本**：

| 脚本 | 查什么 |
|---|---|
| `audit_manuscript.py` | 六维检查：章节完整性、表格合计 vs 正文、图注 vs 图文件、文献格式、假大空/防御型写作、标题主张 vs 效应量 |
| `check_references.py` | 文献联网核验：PMID、DOI、年份、卷期页、第一作者、标题相似度 |
| `check_claims.py` | 回复信声明对账：把每条"已修复"映射回文件验真假 |
| `audit_package.py` | 投稿包：白名单、内部文件、乱码文件名、BOM、图分辨率与色彩 |

**最有用的几个检查**：
- p 值写作 `0.0` 或 `<1e-300` → 直接判阻断（这两个都是真实会犯的错）
- 图注说"标了五个"但图里只有四个 → 标出来请人核对
- 标题写 `independently prognostic` 但 HR < 1.1 → 判阻断
- 表格列名是 `p (sci)` 时 `"p" in df.columns` 为假 → 重算代码静默不执行

**用法**：见上方 Usage。脚本发现阻断项时返回码为 1，可接入 CI。

**要求**：**零个 `✗`，且每个 `⚠` 都必须在报告中写明人工结论，才允许上传。**

**它查不了什么**：图注内容对不对（要人看图数）、引用的文献是否真支持你的主张、假设是否成立、假大空该不该删、数据是否真实存在。这五件事脚本只能把可疑的地方指出来，判断在人。

---

## License

MIT. See [LICENSE](LICENSE).

## Contributing

If you have a check worth adding, open an issue with the concrete case that motivated it. Checks that come with a real failure attached are the most useful.
