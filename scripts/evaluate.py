#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「要求清单」+「逐条判定」合成评估报告。

只做确定性计算与制表：硬门槛判定、扣分累加、得分区间、结论。
语义判断（这条到底符合不符合）由 Agent 完成并写进 assessments.json，本脚本不猜。

用法:
    python evaluate.py --requirements requirements.json \
                       --assessments assessments.json \
                       [--profile company_profile.json] --out ./work
"""

import sys, os, io, json, argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VALID_STATUS = ("PASS", "FAIL", "UNKNOWN", "NA")
LINE_ORDER = {"QUALIFICATION": 0, "CONFORMITY": 1, "SCORING": 2}
LINE_NAME = {"QUALIFICATION": "资质评估（能不能进门）",
             "CONFORMITY": "符合性评估（会不会被判无效）",
             "SCORING": "标准评估（能拿多少分）"}
STATUS_NAME = {"PASS": "符合", "FAIL": "不符合", "UNKNOWN": "资料不足", "NA": "不适用"}
CONCLUSION_NAME = {"DISQUALIFIED": "出局", "PENDING": "待定（资料不足）",
                   "ELIGIBLE": "通过"}


def load(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def as_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def as_num(v):
    try:
        return float(v)
    except Exception:
        return None


def evaluate(reqs_doc, assess_doc):
    reqs = {r["id"]: r for r in reqs_doc.get("requirements", [])}
    items = {a["req_id"]: a for a in assess_doc.get("items", [])}
    model = reqs_doc.get("score_model", {}) or {}
    detail_total = as_num(model.get("detail_total"))
    price_total = as_num(model.get("price_total"))
    # 扣分池基准分：每个池「全满足」即得满分，不满足按项从里面扣。
    # 这一块是「得分」不是「零起扣分」，漏掉它会把整份卷子的分数算少。
    pool_base = sum(as_num(p.get("declared_total")) or 0.0
                    for p in model.get("pools", []))

    rows, missing_assess, bad_status = [], [], []
    hard_fail, hard_unknown = [], []
    gained, gained_worst, lost, lost_worst = 0.0, 0.0, 0.0, 0.0

    ordered = sorted(reqs.values(),
                     key=lambda r: (LINE_ORDER.get(r.get("line"), 9), r["id"]))
    for r in ordered:
        rid = r["id"]
        a = items.get(rid)
        if a is None:
            missing_assess.append(rid)
            a = {"req_id": rid, "status": "UNKNOWN"}
        st = a.get("status", "UNKNOWN")
        if st not in VALID_STATUS:
            bad_status.append("%s=%s" % (rid, st))
            st = "UNKNOWN"

        line = r.get("line", "SCORING")
        hard = bool(r.get("is_hard_gate"))
        per_item = as_num(r.get("per_item"))
        max_score = as_num(r.get("max_score"))
        fail_items = as_int(a.get("fail_items"), 1 if st == "FAIL" else 0)
        unknown_items = as_int(a.get("unknown_items"), 1 if st == "UNKNOWN" else 0)

        deduct, deduct_worst, award, award_worst = None, None, None, None
        if line == "SCORING":
            if per_item is not None:
                deduct = per_item * fail_items
                deduct_worst = per_item * (fail_items + unknown_items)
                lost += deduct
                lost_worst += deduct_worst
            if max_score is not None:
                got = as_num(a.get("awarded"))
                award = got if (st != "UNKNOWN" and got is not None) else (
                    0.0 if st == "UNKNOWN" else 0.0)
                award_worst = got if got is not None else (max_score if st == "UNKNOWN" else 0.0)
                gained += award
                gained_worst += award_worst

        if hard and st == "FAIL":
            hard_fail.append(rid)
        if hard and st == "UNKNOWN":
            hard_unknown.append(rid)

        rows.append({
            "req_id": rid, "line": line, "line_name": LINE_NAME.get(line, line),
            "category": r.get("category", ""), "title": r.get("title", ""),
            "symbol": r.get("severity_symbol") or "", "hard_gate": hard,
            "status": st, "status_name": STATUS_NAME[st],
            "per_item": per_item, "max_score": max_score,
            "fail_items": fail_items, "unknown_items": unknown_items,
            "deduction": round(deduct, 4) if deduct is not None else None,
            "deduction_worst": round(deduct_worst, 4) if deduct_worst is not None else None,
            "awarded": award, "awarded_best": award_worst,
            "evidence": a.get("evidence", []),
            "missing": a.get("missing", ""),
            "note": a.get("note", ""),
            "source_lines": r.get("source_lines", []),
        })

    # 扣分最多把基准分扣光，不会出现负分（扣完为止）
    lost = min(lost, pool_base)
    lost_worst = min(lost_worst, pool_base)
    if detail_total is not None:
        lo = max(0.0, min(detail_total, pool_base + gained - lost_worst))
        hi = max(0.0, min(detail_total, pool_base + gained_worst - lost))
    else:
        lo = hi = None

    if hard_fail:
        conclusion = "DISQUALIFIED"
    elif hard_unknown:
        conclusion = "PENDING"
    else:
        conclusion = "ELIGIBLE"

    counts = {}
    for r in rows:
        k = (r["line"], r["status"])
        counts[k] = counts.get(k, 0) + 1

    def tally(ln):
        return {s: counts.get((ln, s), 0) for s in VALID_STATUS}

    return {
        "tender": reqs_doc.get("tender", {}),
        "company": assess_doc.get("company", ""),
        "conclusion": conclusion,
        "conclusion_name": CONCLUSION_NAME[conclusion],
        "hard_fail": hard_fail,
        "hard_unknown": hard_unknown,
        "score_model": model,
        "detail_score_range": {"low": round(lo, 2) if lo is not None else None,
                               "high": round(hi, 2) if hi is not None else None,
                               "detail_total": detail_total,
                               "pool_base": round(pool_base, 2),
                               "additive_max": round(
                                   sum(as_num(r.get("max_score")) or 0.0
                                       for r in reqs.values()
                                       if r.get("line") == "SCORING"), 2),
                               "lost": round(lost, 2), "lost_worst": round(lost_worst, 2),
                               "gained": round(gained, 2), "gained_best": round(gained_worst, 2)},
        "price_score": {"value": None,
                        "note": "报价分需开标后由评审委员会按基准价计算，本评估不预测"},
        "tally": {ln: tally(ln) for ln in LINE_ORDER},
        "rows": rows,
        "integrity": {"missing_assessment": missing_assess,
                      "invalid_status": bad_status},
    }


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def render(res):
    t = res["tender"]
    L = []
    L.append("# 投标公司符合性评估报告")
    L.append("")
    L.append("- 采购项目：%s" % (t.get("name") or "（未填写）"))
    L.append("- 项目编号：%s" % (t.get("code") or "（未填写）"))
    L.append("- 采购人：%s" % (t.get("buyer") or "（未填写）"))
    L.append("- 受评公司：%s" % (res.get("company") or "（未填写）"))
    L.append("- 最高限价：%s" % ("（未识别）" if t.get("ceiling") in (None, "") else t.get("ceiling")))
    L.append("")
    L.append("## 一、结论速览")
    L.append("")
    L.append("**结论：%s**" % res["conclusion_name"])
    L.append("")
    L.append(md_table(["评估线", "符合", "不符合", "资料不足", "不适用"],
                      [[LINE_NAME.get(k, k), v["PASS"], v["FAIL"], v["UNKNOWN"], v["NA"]]
                       for k, v in res["tally"].items()]))
    L.append("")
    if res["hard_fail"]:
        L.append("**出局原因**（不满足即判无效，不可补救）：%s" % "、".join(res["hard_fail"]))
        L.append("")
    if res["hard_unknown"]:
        L.append("**待补资料**（未证明即视为不满足）：%s" % "、".join(res["hard_unknown"]))
        L.append("")
    sr = res["detail_score_range"]
    if sr["detail_total"] is not None:
        L.append("详细评审得分区间：**%.2f ~ %.2f** / 满分 %.2f 分（报价分 %s 分不预测）"
                 % (sr["low"], sr["high"], sr["detail_total"],
                    res["score_model"].get("price_total", "?")))
        L.append("")
        L.append("> 区间含义：下限=所有「资料不足」按不满足计；上限=所有「资料不足」按满足计。"
                 "区间越宽，说明资料缺口越大。")
        L.append("")
        L.append("分数怎么来的：扣分池基准 %.2f 分（全部满足即得，按项扣）＋加分项满分 %.2f 分 ＝ 满分 %.2f 分。"
                 % (sr["pool_base"], sr["additive_max"], sr["detail_total"]))
        L.append("")
        L.append("| 口径 | 扣分 | 加分 | 合计 |")
        L.append("|---|---|---|---|")
        L.append("| 最差（资料不足全按不满足） | -%.2f | +%.2f | %.2f |"
                 % (sr["lost_worst"], sr["gained"], sr["low"]))
        L.append("| 最好（资料不足全按满足） | -%.2f | +%.2f | %.2f |"
                 % (sr["lost"], sr["gained_best"], sr["high"]))
        L.append("")

    for ln in ("QUALIFICATION", "CONFORMITY", "SCORING"):
        sub = [r for r in res["rows"] if r["line"] == ln]
        if not sub:
            continue
        L.append("")
        L.append("## %s" % LINE_NAME[ln])
        L.append("")
        if ln == "SCORING":
            L.append(md_table(["编号", "类别", "符号", "要求摘要", "判定",
                               "扣分/得分", "区间贡献", "证据", "缺什么"],
                              [[r["req_id"], r["category"], r["symbol"] or "-",
                                (r["title"] or "")[:40], r["status_name"],
                                ("" if r["deduction"] is None else "-%.2f" % r["deduction"])
                                + ("" if r["awarded"] is None else "+%.2f" % r["awarded"]),
                                ("" if r["deduction_worst"] is None else
                                 "最差再 -%.2f" % (r["deduction_worst"] - r["deduction"]))
                                + ("" if r["awarded_best"] is None else
                                   " 最好再 +%.2f" % (r["awarded_best"] - (r["awarded"] or 0))),
                                ",".join(r["evidence"]) or "-", r["missing"] or "-"]
                               for r in sub]))
        else:
            L.append(md_table(["编号", "类别", "符号", "是否硬门槛", "要求摘要",
                               "判定", "证据", "缺什么", "原文行号"],
                              [[r["req_id"], r["category"], r["symbol"] or "-",
                                "是" if r["hard_gate"] else "否",
                                (r["title"] or "")[:44], r["status_name"],
                                ",".join(r["evidence"]) or "-", r["missing"] or "-",
                                ",".join(str(x) for x in r["source_lines"]) or "-"]
                               for r in sub]))
    L.append("")
    L.append("## 五、本报告不做什么")
    L.append("")
    L.append("- 不编写投标文件、不代填响应表、不生成报价。")
    L.append("- 不预测报价分与其他投标人的得分。")
    L.append("- 不对「资料不足」做任何推断；缺就是缺。")
    L.append("- 结论仅供内部判断，不构成对评审结果的保证。")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--assessments", required=True)
    ap.add_argument("--profile")
    ap.add_argument("--out", default="./work")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    reqs_doc = load(a.requirements)
    assess_doc = load(a.assessments)
    res = evaluate(reqs_doc, assess_doc)

    jp = os.path.join(a.out, "evaluation.json")
    with io.open(jp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    mp = os.path.join(a.out, "评估报告.md")
    with io.open(mp, "w", encoding="utf-8") as f:
        f.write(render(res))

    print("结论: %s" % res["conclusion_name"])
    if res["hard_fail"]:
        print("出局项: %s" % ", ".join(res["hard_fail"]))
    if res["hard_unknown"]:
        print("待补资料项: %s" % ", ".join(res["hard_unknown"]))
    sr = res["detail_score_range"]
    if sr["detail_total"] is not None:
        print("详细评审区间: %.2f ~ %.2f / %.2f" % (sr["low"], sr["high"], sr["detail_total"]))
    if res["integrity"]["missing_assessment"]:
        print("!! 未判定的要求: %s" % ", ".join(res["integrity"]["missing_assessment"]))
    if res["integrity"]["invalid_status"]:
        print("!! 非法状态值: %s" % ", ".join(res["integrity"]["invalid_status"]))
    print("产出: %s / %s" % (jp, mp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
