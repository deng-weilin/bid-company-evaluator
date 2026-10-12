# 五步作业流程

约定工作目录：`./work/`（可用 `--out` 改）。所有中间产物都落在这里。

## S0 固化原文

```bash
python scripts/extract_tender.py <招标文件.docx> [<招标文件.pdf>] --out ./work --tag tender
```

产出：
- `work/tender_raw.tender.txt` —— 行号即后续所有 `source_lines` / `locator`
- `work/source_fingerprint.tender.json` —— sha256、章节骨架、**符号逐行台账**
- `work/extract_index.json`

必做：
1. docx 与 pdf **都传**。只传一个，另一个的差异无从发现。
2. 看到 `!! 检出「以 PDF 为准」类声明` → 必须按 `severity-symbols.md` 第五节做双版本比对。
3. pdf 显示 `[跳过]`（环境无解析器）→ 用 Read 工具直接读 pdf 比对关键表；仍做不了就在 `requirements.json` 里把 `pdf_checked` 填 `false`，并在报告里写明。
4. **换抽取脚本或改抽取逻辑后必须重跑**，否则行号全错位。

## S1 拆要求

读 `work/tender_raw.tender.txt`，**必须跨章联读**：

| 内容 | 通常在第几章 |
| --- | --- |
| 资格条件 | 第一章 + 第五章"资格审查" |
| ★ 实质性要求 | 第二章 2.4 系列 + 第三章带 ★ 条款 + 第三章商务要求 |
| 技术/服务标准与符号 | 第三章 3.2 / 3.3 |
| 分值池与扣分规则 | 第五章"评审细则及标准" |
| 响应文件格式与签章 | 第六章 |

只读一章不得声称完成。没读的章节写进 `issues[]`。

产出 `work/requirements.json`（模板见 `assets/requirements.template.json`）：

1. 逐条拆，稳定 ID `REQ-001`。
2. 每条填 `line`（三选一）、`category`、`title`、`text`、`quote`、`source_lines`。
3. `severity_symbol` 填 ★▲█● 或 `null`。
4. `is_hard_gate`：★ 与资格条件 = `true`；其余 = `false`。
5. `per_item` / `max_score`：**原文没写分值就填 `null`**，不许估。且**两者互斥**——
   - 原文是"不满足扣 N 分" → 填 `per_item`，`max_score` 留 `null`（扣分项）；
   - 原文是"每有 1 个得 N 分，最多 M 分" → 填 `max_score`，`per_item` 与 `severity_symbol` 都留 `null`（加分项）。
   
   判别不清就看方向：**往下扣**是扣分项，**往上加**是加分项。详见 `severity-symbols.md` 第三节。
6. 建 `score_model.pools`：原文明确"每有一项X不满足扣N分（共M条）"才建池，含 `source_line` 与 `quote`。**无符号条款也要建池**。加分项不进池。
7. 填 `coverage_ledger`：把 `source_fingerprint` 里每个符号行号逐行登记 COVERED 或 EXEMPT+理由（键是 符号+行号，同一行可有多个符号）。
8. 交 S4 前自查：`sum(pools.declared_total) + sum(加分项 max_score) == detail_total`。对不上就是漏拆了要求。

## S2 企查查取证

**顺序不能反：先查企查查，再要原件。** 企查查能查到的一律以企查查为准，避免只拿到公司自报的漂亮数字。

工具清单与甄别规则详见 `references/qcc-sourcing.md`。

### S2.1 锚定主体

```
get_company_by_query(searchKey = 公司全称)
```

- 唯一精确匹配 → 取统一社会信用代码，**后续一律传信用代码，不传公司名**。
- 多候选 → **停下来让用户选**，自动选排名第一是错误行为。
- 未匹配 → 让用户核对名称（曾用名、多字少字、"四川" vs "四川省"）。

### S2.2 按线拉数据

- **资质线**：`get_company_registration_info`、`get_dishonest_info`、`get_serious_violation`、
  `get_business_exception`、`get_administrative_penalty(date_from=三年前的日期)`、
  `get_tax_violation`、`get_judgment_debtor_info`、`get_annual_reports`、`get_financial_data`、
  `get_shareholder_info`、`get_actual_controller`。
- **符合性线**：`get_qualifications(status="有效")`、`get_company_profile`。
- **标准线**：`get_software_copyright_info`、`get_patent_info`、`get_trademark_info`、
  `get_bidding_info(role="中标方", date_from=招标要求的起始日)`。

### S2.3 三道甄别（不做完不许进 S3）

1. **相关性**：软著、专利、业绩要**逐个看名称**是否落在招标限定的领域。查到 N 条 ≠ N 条都算分。
2. **去重**："中选候选人公示" 与 "结果公告" 是同一个项目，只记一次。按招采单位 + 项目名 + 金额去重。
3. **主体一致**：证书、软著、业绩的权属人必须是受评公司本身，母子公司、兄弟公司不算。

### S2.4 补企查查查不到的

| 补什么 | 怎么补 |
| --- | --- |
| **政府采购严重违法失信名单** | **必须**另查 ccgp.gov.cn 留截图。企查查不覆盖，且是硬门槛 |
| 平台运行数据、功能截图、现场演示 | 向公司要 |
| 合同关键页、等保备案证明、审计报告 | 向公司要原件 |
| 人员配置表、实施方案、售后服务方案 | 向公司要 |
| 承诺函意愿 | 问公司确认，登记进 `declarations` |

用 `assets/公司资料采集表.md` 收，`source` 标 `USER` 或 `WEB`。

### S2.5 落库

复制 `assets/company_profile.template.json` 为 `work/company_profile.json`。
每份证据进 `evidence_index`，必须标 `source`（`QCC` / `WEB` / `USER`）；`source=QCC` 必须带 `tool` 与 `fetched_at`。

> 拿不到就是 `UNKNOWN`，这是正确结果，不是失败。**资料库为空 → 后面全部判 `UNKNOWN`**，结论为"待定"。

## S3 逐条判定

产出 `work/assessments.json`（模板见 `assets/assessments.template.json`）。

- 一条要求一条判定，不合并、不省略。
- 状态只有 `PASS` / `FAIL` / `UNKNOWN` / `NA` 四个。
- `UNKNOWN` 必填 `missing`（缺哪一份具体材料）。
- 判定口径见 `references/judgement-rules.md`，资料边界见 `references/profile-guide.md`。
- 遇到原文矛盾、条数对不上、版本冲突 → 登记 `issues[]`，**不自行取舍**。

## S4 计算与校验

```bash
python scripts/evaluate.py --requirements work/requirements.json \
                           --assessments work/assessments.json \
                           --profile work/company_profile.json --out ./work
python scripts/validate.py --work ./work --profile work/company_profile.json
```

产出 `work/evaluation.json` 与 `work/评估报告.md`（表格由脚本生成，不含自由发挥的分数）。

**ERROR 未清零，不得交付。** WARN 要逐条处理或在报告里写明理由。

规则表（validate.py）：

| 规则 | 拦什么 |
| --- | --- |
| R1 | 每条要求都有判定；不出现凭空判定 |
| R2 | 状态值合法 |
| R3 | `UNKNOWN` 必填缺什么 |
| R4 | 硬门槛不满足 → 结论必须是"出局"；反之不得误判出局 |
| R5 | 分值池闭合；声明条数 vs 实际条数（WARN） |
| R6 | 单条扣分必须有原文分值池支撑，禁止估分 |
| R7 | 得分区间不越界、不颠倒 |
| R8 | 证据编号必须在资料库里存在 |
| R9 | 覆盖台账逐行闭合（源里每个符号位置都要登记） |
| R10 | 原文引句必须与抽取文本对得上 |
| R11 | 证据来源标注完整：`source` 三选一；`QCC` 必须带 `tool` 与 `fetched_at` |
| R12 | 判"符合"必须挂证据编号，不许空口 PASS |
| R13 | 总分闭合：扣分池合计 + 加分项满分 == 详细评审总分 |

改完脚本跑一次 `python scripts/self_test.py`（1 金样例 + 5 变异），必须全绿。

## S5 交付

`present_files` 交付 `work/评估报告.md` + `work/evaluation.json`。

回复用户时必须包含：
1. **结论**（出局 / 待定 / 通过）与出局或待定的具体条目；
2. **得分区间**与区间宽度说明（区间越宽 = 资料缺口越大）；
3. **最紧急的 3 个缺口**（按"是不是硬门槛"排序）；
4. **企查查查到但经甄别不算数的项**（软著不相关、业绩重复、主体不符）——这是防止"查到即算数"的关键交代；
5. **明确声明本报告不做什么**。

## 常见坑

1. **只拆第三章。** 资格条件在第一章、扣分规则在第五章，漏读必漏项。
2. **用符号总数做对账。** 见 `severity-symbols.md` 第二节，这是本项目文件上真实踩过的坑（▲ 出现 13 次但只声明 12 条）。
3. **把"资料不足"写成"符合"。** 最高频的幻觉。
4. **无符号条款整块漏。** 扫符号扫不到，但它们也要扣分。
5. **报价分乱猜。** 报价分要开标后才知道，一律写不适用。
6. **"承诺即可得分"和"必须拿证据"混为一谈。** 看原文写的是"须提供承诺函"还是"须提供证明材料"。
7. **改了抽取脚本不重跑。** 行号全错位，溯源链断在看不见的地方。
8. **加分项被当成无符号扣分项。** 声明"共 25 条"却登记出 29 条，多出来的就是带 `max_score` 的加分项。R5 会 WARN，别当噪音。
9. **把扣分池当成"零起扣分"。** 池的 `declared_total` 是**全满足就能拿到的基准分**，不满足才扣。漏掉基准分会整份卷子少算一大截（真实项目上少算 48 分）。
10. **总分凑不平就往下走。** 48 + 42 ≠ 90 说明还有分没拆成要求，R13 会拦——别手动改总分去凑。
