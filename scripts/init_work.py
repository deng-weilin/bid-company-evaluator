#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 work/ 骨架：把 assets/ 下的三份模板拷成待填的 json，并写一份填写说明。

用法:
    python init_work.py [--out ./work]

零第三方依赖。已有同名文件时跳过（不覆盖，避免毁掉已填内容）。
"""

import sys, os, io, json, shutil, argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")

PAIRS = [
    ("requirements.template.json", "requirements.json",
     "S1 产出：把招标文件拆成逐条要求。字段说明在模板里。"),
    ("assessments.template.json", "assessments.json",
     "S3 产出：一条要求一条判定。status 只能填 PASS/FAIL/UNKNOWN/NA。"),
    ("company_profile.template.json", "company_profile.json",
     "S2 产出：公司事实库 + 证据索引。所有证据必须有编号与来源。"),
]

README = """# work/ 目录说明

| 文件 | 谁生成 | 说什么 |
| --- | --- | --- |
| `tender_raw.<tag>.txt` | S0 `extract_tender.py` | 招标文件逐行底稿，**行号就是溯源坐标** |
| `source_fingerprint.<tag>.json` | S0 | 原文指纹（sha256、章节骨架、符号出现台账） |
| `requirements.json` | S1 人工/半自动 | 三条线的要求清单 + 分值池 + 覆盖台账 |
| `company_profile.json` | S2 企查查取证 | 公司事实库 + 证据索引（每条证据要能追到工具） |
| `assessments.json` | S3 人工判定 | 逐条判定结果 |
| `evaluation.json` | S4 `evaluate.py` | 汇总：结论、得分区间、明细 |
| `评估报告.md` | S4 `evaluate.py` | 给人看的报告 |

## 顺序

```bash
python scripts/extract_tender.py <文件.docx> [<文件.pdf>] --out ./work --tag tender
# —— S1 拆要求、S2 企查查取证、S3 逐条判定（这三步由 Agent 完成）——
python scripts/evaluate.py --requirements work/requirements.json \\
                           --assessments work/assessments.json \\
                           --profile work/company_profile.json --out ./work
python scripts/validate.py --work ./work --profile work/company_profile.json
python scripts/pentest.py  --work ./work --profile work/company_profile.json
```

`pentest.py` 需要 work/ 里已有三份 json，所以放在最后跑。
`validate.py` 报 ERROR 一律不许交付。WARN 要逐条说明为什么可以不改。
全套 16 条校验（R1-R17）之外，`pentest.py` 再用 10 份坏数据验证这些校验本身能不能被绕过去。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./work")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)

    for src, dst, desc in PAIRS:
        p = os.path.join(ASSETS, src)
        if not os.path.exists(p):
            print("[跳过] 模板不存在: %s" % p)
            continue
        d = os.path.join(out, dst)
        if os.path.exists(d):
            print("[保留] %s 已存在，不覆盖" % dst)
            continue
        shutil.copyfile(p, d)
        print("[生成] %s —— %s" % (dst, desc))

    rp = os.path.join(out, "README.md")
    if not os.path.exists(rp):
        with io.open(rp, "w", encoding="utf-8") as f:
            f.write(README)
        print("[生成] README.md —— 目录说明与命令顺序")

    print("work 目录: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
