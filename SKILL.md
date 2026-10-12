---
name: bid-company-evaluator
display_name: 投标公司符合性评估器
display_name_en: Bid Company Eligibility Evaluator
description: 拿一份招标/磋商/询价文件，对一家投标公司做资质评估、符合性评估与标准评估，先经企查查取证再做逐条判定，判断是否符合招标文件各项要求，给出出局/待定/通过结论与得分区间；不编写投标文件、不生成报价、不代提交。用户提到评估投标公司、判断能不能投、资格符合性审查、资质打分测算、投标公司摸底或第三方公司投标能力评估时使用。
description_zh: 通用评审器——招标文件加企查查取证，输出三条评估线逐条判定、结论与得分区间，全程可溯源、零资料幻觉、不参与投标。
description_en: Evaluate any bidding company against any tender document using QCC company data - qualification, conformity and standard compliance, with pass/fail/unknown verdicts and a score range. Never writes bid documents.
version: 0.4.0
author: 邓伟林
user-invocable: true
agent_created: true
---

# 投标公司符合性评估器

**通用评审器**：不预设投标主体。谁的资料喂进来就评谁——自家的、竞争对手的、合作方的都行。

输入：招标文件 + 一家公司的客观资料。
输出：三条评估线的逐条判定 + 出局/待定/通过结论 + 详细评审得分区间。
**不输出**：投标文件、响应表、报价、评分排名预测。

## 边界（违反即停止）

1. **零资料幻觉。** 公司资质、业绩、人员、财务只能来自 `company_profile.json` 或用户明确指定的资料目录。拿不出材料一律记 `UNKNOWN`（资料不足），**禁止推断、类比、常识补全**。
2. **不猜分值。** 原文没写分值就写 `null`。所有扣分必须能回指到评标办法原文的行号与引句。
3. **不裁定冲突。** 声明条数与实际条数不符、docx 与 pdf 不一致、条款歧义，一律登记 `issues[]` 交人工。
4. **不做总量对账，只做逐行台账。** 禁止用"符号出现次数 == 产出条数"校验。评分规则描述句会在一行内引用多个符号，总量比对既漏报也误报。必须对源文本每个符号行号逐行登记处置，由 R9 校验。
5. **不参与投标。** 不写标书章节、不填响应表、不生成报价、不预测报价分与排名。
6. **公司事实必须过企查查，且"查到"不等于"符合"。** 资质、知识产权、业绩、信用一律先用企查查取证；取到后必须做三道甄别——**相关性**（查到 N 个软著不等于 N 个都算分）、**去重**（"中选候选人公示"与"结果公告"是同一个项目）、**主体一致**（母子公司、兄弟公司的不算）。企查查查不到的部分（平台运行数据、合同关键页、等保备案、承诺函意愿、政府采购严重违法失信名单）回头找公司要或另行官网查，要不到就记 `UNKNOWN`。
7. **先分清"加分项"和"扣分项"，再谈算分。** 标准线里混着两类东西：
   - **扣分项**：带 ▲█● 或不带符号的技术条款，全满足即拿满该池分数，不满足按项从池里扣 → 用 `severity_symbol` + `per_item`。
   - **加分项**：按数量给分的（软著几个、业绩几个、实施方案主观分）→ 用 `max_score`，**不带 `severity_symbol` 也不进任何扣分池**。
   
   两类混在一起，条数永远对不上、总分永远算不平。R5 只在扣分项里数条数，R13 校验"扣分池合计 + 加分项满分 == 详细评审总分"。
8. **判定值说了算，手填的分值不作数。** `status` 与 `fail_items` / `unknown_items` / `awarded` 三者必须自洽；不服就报错（R14/R15），不许静默改数过关。典型陷阱：判"不符合"却把 `fail_items` 写成 0 → 一分不扣；判"不符合"却填了 `awarded` → 照拿满分。这两条都不报错不告警，只有全量跑才发现分数不对。
9. **各线条款总数要平账。** 符号台账（R9）和分值闭合（R13）只管得着"带符号"和"计分"的条款——符合性线里那些不计分的要求，**整条漏拆机器也发现不了**。所以拆条时必须人工从原文数出三线总数写进 `line_totals`，由 R17 核对。这是唯一能防"拆漏一整条线"的手段。

## 五步流程

| 步 | 做什么 | 主要产物 |
| --- | --- | --- |
| **S0 固化原文** | 抽取 docx/pdf 为可逐行溯源的底稿 | `tender_raw.<tag>.txt`、`source_fingerprint.<tag>.json` |
| **S1 拆要求** | 跨章联读，拆成三条线的要求清单 | `requirements.json` |
| **S2 企查查取证** | 锚定主体 → 按线拉企查查数据 → 三道甄别 → 补官网与公司原件 | `company_profile.json` |
| **S3 逐条判定** | 一条要求一条判定 | `assessments.json` |
| **S4 计算校验** | 脚本算分制表 + 门禁校验 | `evaluation.json`、`评估报告.md` |

完整作业手册见 @references/workflow.md。

```bash
python scripts/extract_tender.py <文件.docx> [<文件.pdf>] --out ./work --tag tender
python scripts/evaluate.py --requirements work/requirements.json \
                           --assessments work/assessments.json \
                           --profile work/company_profile.json --out ./work
python scripts/validate.py --work ./work --profile work/company_profile.json
python scripts/pentest.py  --work ./work --profile work/company_profile.json   # 改了脚本必跑
```

## 三条评估线

| 线 | 判什么 | 不满足的后果 |
| --- | --- | --- |
| **资质评估** `QUALIFICATION` | 主体资格、政策资格、特定资格、信用记录 | 出局 |
| **符合性评估** `CONFORMITY` | 带星号的实质性要求、有效期、报价、签章、知识产权 | 判无效响应 |
| **标准评估** `SCORING` | 符号条款与无符号技术条款的扣分、以及加分项 | 扣分 |

顺序不能反。前一线没过，后一线的分数没有意义（但仍要列出，供"补什么能救回来"用）。

判定值只有四个：`PASS` 符合 / `FAIL` 不符合 / `UNKNOWN` 资料不足 / `NA` 不适用。
`UNKNOWN` 必须写明缺哪一份具体材料。

口径细节见 @references/judgement-rules.md（含黑话白话对照表）。

## 关键实现

- **得分区间，不是一个数。** 下限=所有"资料不足"按不满足计；上限=按满足计。区间越宽说明资料缺口越大。
- **扣分池是基准分，不是零起扣分。** 每个池"全满足"即得该池满分（各池 `declared_total` 之和 = 扣分池基准分），不满足按项从基准里扣，扣完为止不为负。加分项另算。两者相加才是满分。
- **报价分一律不适用**，报告里写明"需开标后按基准价计算，本评估不预测"。
- **硬门槛自动推导结论**：任一硬门槛 `FAIL` 出结论"出局"；无一 FAIL 但有 `UNKNOWN` 出"待定"；全部 PASS 出"通过"。由 R4 双向校验。
- **覆盖台账** `coverage_ledger`：源里每个符号行号都要登记 `COVERED` 或 `EXEMPT` 加理由。台账键是 **(符号, 行号)**，不是行号——同一行可能同时出现 ★▲█●。
- **分值池** `score_model.pools`：原文明确"每有一项 X 不满足扣 N 分（共 M 条）"才建池；无符号条款也要建池。R5 校验条数与乘法闭合，R6 禁止无依据扣分，R13 校验总分闭合（**pools 为空也要平账**）。
- **判定值优先于手填分值**：`evaluate.py` 按 `status` 反推扣分项数与得分，再把不一致处写进报告第四节"算分口径被自动纠正的地方"，由 R14/R15 拦截。
- **★ 一定标硬门槛**（R16）。漏标会让"出局"静默降级成"待定/通过"，且不报任何错——这是本 skill 被实测打穿过的最危险一处。
- **红队自检** `pentest.py`：主动构造坏数据，验证"有人把关掉校验后能不能悄悄过关"。这不是测"算得对不对"，是测"能不能被绕过"。

符号建模与"以 PDF 为准"陷阱见 @references/severity-symbols.md。
公司资料填报与零幻觉边界见 @references/profile-guide.md。
**企查查取证规范（S2 必读）见 @references/qcc-sourcing.md**——必查工具清单、查不到的部分、三道甄别、中小企业资格隐藏雷。
**完整实测样例见 @references/case-study.md**——真实项目跑通 90 条的全流程与四个踩坑点。

## 包结构

```text
SKILL.md                              本文件：边界、五步流程、三条线
references/workflow.md                S0-S5 作业手册、规则表、常见坑
references/judgement-rules.md         三态判定、硬门槛与软失分、算分区间、黑话白话对照
references/severity-symbols.md        符号建模、加分项/扣分项、逐行台账、分值池闭合、PDF 陷阱
references/profile-guide.md           资料填报、证据编号、承诺函怎么算、填不出来的写法
references/qcc-sourcing.md            企查查取证：工具清单、查不到的部分、三道甄别、主体锚定
references/case-study.md              真实项目实测：90 条判定、48+42 闭合、四个踩坑点
scripts/extract_tender.py             docx/pdf 转带行号底稿加指纹加符号台账（零依赖）
scripts/init_work.py                  从模板生成 work/ 骨架（三份 json + 说明）
scripts/evaluate.py                   要求加判定转判定表、区间、结论、报告 md
scripts/validate.py                   R1-R17 门禁校验
scripts/self_test.py                  自检：1 金样例加 5 个应被拦截的变异
scripts/pentest.py                    红队自检：10 个「坏数据」用例，验证能不能被绕过
assets/requirements.template.json     要求清单模板（含字段取值说明）
assets/assessments.template.json      逐条判定模板
assets/company_profile.template.json  公司事实库模板
assets/公司资料采集表.md               发给被评公司填的白话表单
```

改动脚本后两个都要跑，必须全绿：`self_test.py`（6 项，测算得对不对）+ `pentest.py`（10 项，测能不能被绕过）。

## 交付

交付 `work/评估报告.md` 与 `work/evaluation.json`。**交付前 `validate.py` 必须 0 ERROR**（WARN 需逐条说明原因）。

回复必须包含：结论与出局或待定条目、得分区间与宽度说明、最紧急的 3 个缺口（按是否硬门槛排序）、**企查查查到但经甄别不算数的项**（软著不相关、业绩重复、主体不符），以及"本报告不做什么"的声明。
