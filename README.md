# pre-submission-audit

**A pre-submission checker for scientific manuscripts, built after four consecutive rejections that were all caused by the same thing: sentences in our documents that our own files did not support.**

[中文说明见下](#中文说明)

---

## Why this exists

This tool was not written because we wanted a linter. It was written because we submitted the same manuscript to a journal four times and were rejected four times, and in every round the science was fine and the reporting was not:

| Round | What the reviewer found |
|---|---|
| 1 | A figure legend from a **different project** had been copied into the submission package |
| 2 | An **internal to-do list** — containing local file paths and our own prediction that the paper would be rejected again — was packaged with the manuscript |
| 3 | The response letter contained **five claims of "Fixed"** that were not true of the submitted files |
| 4 | **34 cells** across four tables reported `p < 1e-300`; the true values were around `1e-15` |

None of these were errors of analysis. Every one of them was a **claim that could have been checked in ten seconds and was not**.

The reviewer's closing line in round four was:

> Academic integrity is not only not fabricating. It is writing sentences that survive being checked against your own tables.

This repository is the check we should have run ourselves.

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
- Resolution < 300 dpi, colour mode (CMYK vs RGB)
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
- Repeated 6-grams (same idea stated several times)
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
pip install python-docx pandas numpy requests pillow
```

No installation step beyond the dependencies. Python ≥ 3.9.

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

**Rule: zero `✗` and every `⚠` explicitly resolved in the report before you upload.**

---

## The six traps this was built around

Each of these actually happened.

### 1. `scipy.stats.spearmanr` underflows to zero

```python
# Wrong: returns p = 0.0 for large n, which gets misread as "< any value"
rho, p = stats.spearmanr(x, y)

# Right: t approximation, no underflow
t = rho * np.sqrt((n - 2) / (1 - rho ** 2))
p = 2 * stats.t.sf(abs(t), df=n - 2)
```

We reported `p < 1e-300` in 34 cells. The true value for the main compound was `1.88e-15` — and the correct value was already printed **in our own figure**. Four rounds passed before an outside reader recomputed it.

### 2. `if "p" in df.columns` fails silently

When the column is named `p (sci)`, the condition is `False`, the recomputation block never runs, and nothing is reported. Match column names loosely, and print which columns were actually processed.

### 3. "The model did not converge" — suspect the script first

Three of six cohorts "failed to converge". The cause was a line that silently dropped cohorts with missing age. **Diagnostic: fit a single-covariate model. If it converges, the problem is your script, not your data.**

### 4. Global string replacement corrupts meaning

Replacing `p < 1×10⁻¹⁵` with `p = 1.9×10⁻¹⁵` also rewrote the Methods sentence that stated the *general* reporting convention, turning a specific value into a universal rule. Re-read every occurrence after a global replace.

### 5. A legend can claim something the figure does not show

"The five compounds with the largest |ρ| are labelled" — four were labelled, and they were not the top four. **Open the image and count.**

### 6. Internal files end up in the submission package

A to-do list, a note containing `D:\project\...`, a filename mangled by double encoding. **Build packages from an explicit whitelist, never by copying a directory.**

---

## Making your response letter machine-checkable

`check_claims.py` will reveal something uncomfortable: most response letters are unverifiable, because they say "I confirmed" instead of naming a value.

| ✗ Unverifiable | ✓ Verifiable |
|---|---|
| Fixed the reference list | References expanded from **10 to 14** |
| Corrected the p-values | Dasatinib p changed from `<1e-300` to **1.88e-15** |
| Removed the ghost cohort sentence | Removed `"two small cohorts (n = 27 each)"`; grep returns **0** |
| Updated Table S4 | `n_uni` sum = **3,291**; `ev_uni` = **823** |

Three rules:
1. **Give numbers** — before → after, both values
2. **Give strings** — put deleted/added text in backticks so it can be grepped
3. **Give the check** — `grep "xxx" → 0` when relevant

---

## What this tool cannot do

Stated plainly, because over-claiming is exactly the failure mode it was built to catch.

1. **Legend vs figure content** — "five compounds labelled" needs a human to count. The script only flags it.
2. **Whether a citation supports the claim** — the script verifies a paper exists and is cited correctly. It cannot tell whether that paper actually showed what you say it showed.
3. **Whether a hypothesis holds** — the script compares wording to effect sizes. It cannot judge whether your interpretation is right.
4. **Empty and defensive phrasing** — the script surfaces candidates; deletion is a judgement call.
5. **Fabricated data** — the script checks that figures and tables agree. It cannot check that the underlying measurements were real.

For those five, the tool points at the suspect and stops.

---

## 中文说明

**一句话**：这是一个投稿前的机器终检工具，起因是同一篇稿子连投四轮全被拒，而四次拒稿的理由都不是科学问题，是"写的句子和自己的文件对不上"。

**四次的具体死因**：
1. 别的项目的图注混进了投稿包
2. 内部待办清单（含本机路径和"可能还会被拒"的自我预判）被打包进去
3. 回复信里有五处"已修复"其实没做
4. 四张表 34 个单元格写 `p < 1e-300`，真实值是 `1e-15` 量级

**六个维度**：结构 / 数据一致性 / 图像一致性 / 文献真实性 / 写作质量 / 假设与主张。

**四个脚本**：
- `audit_manuscript.py` — 六维检查
- `check_references.py` — 文献联网核验（PMID、DOI、年份、卷期页、作者序、标题相似度）
- `check_claims.py` — 回复信声明对账
- `audit_package.py` — 投稿包检查

**用法**：见上方 Usage。全部脚本发现阻断项时返回码为 1，可接入 CI。

**要求**：**零个 `✗`，且每个 `⚠` 都必须在报告中写明人工结论，才允许上传。**

---

## License

MIT. See [LICENSE](LICENSE).

## Contributing

If you have a rejection story caused by a checkable oversight, open an issue. The checks in this repo were all written the hard way; additions that come with a real failure attached are the most welcome.
