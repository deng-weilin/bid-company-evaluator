#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对评估产物做门禁校验。任何 ERROR 未清零，不得把报告交给用户。

用法:
    python validate.py --work ./work [--profile company_profile.json]

读取 work/ 下的 requirements.json / assessments.json / evaluation.json /
source_fingerprint.*.json / tender_raw.*.txt。
返回码: 0 = 通过（可能有 WARN）; 1 = 存在 ERROR。
"""

import sys, os, io, json, glob, argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def as_i(v, default=0):
    """把 fail_items / unknown_items 之类转成 int，非法值按 default。"""
    try:
        return int(v)
    except Exception:
        return default


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, rule, msg):
        self.rows.append((level, rule, msg))

    def error(self, rule, msg):
        self.add("ERROR", rule, msg)

    def warn(self, rule, msg):
        self.add("WARN", rule, msg)

    @property
    def n_error(self):
        return sum(1 for r in self.rows if r[0] == "ERROR")

    @property
    def n_warn(self):
        return sum(1 for r in self.rows if r[0] == "WARN")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="./work")
    ap.add_argument("--profile", default=None)
    a = ap.parse_args()
    W = a.work
    rep = Report()

    rq_p = os.path.join(W, "requirements.json")
    as_p = os.path.join(W, "assessments.json")
    ev_p = os.path.join(W, "evaluation.json")
    for p in (rq_p, as_p, ev_p):
        if not os.path.exists(p):
            rep.error("R0", "缺少产物文件: %s" % p)
    if rep.n_error:
        dump(rep)
        return 1

    rq = load(rq_p)
    asd = load(as_p)
    ev = load(ev_p)
    reqs = rq.get("requirements", [])
    items = {x["req_id"]: x for x in asd.get("items", [])}

    # R1 每条要求都有判定
    for r in reqs:
        if r["id"] not in items:
            rep.error("R1", "%s 缺判定" % r["id"])
    for rid in items:
        if rid not in {r["id"] for r in reqs}:
            rep.error("R1", "判定 %s 在要求清单里不存在（凭空判定）" % rid)

    # R2 状态值合法
    for rid, it in items.items():
        if it.get("status") not in ("PASS", "FAIL", "UNKNOWN", "NA"):
            rep.error("R2", "%s 状态值非法: %r" % (rid, it.get("status")))

    # R3 资料不足必须写清缺什么
    for rid, it in items.items():
        if it.get("status") == "UNKNOWN" and not (it.get("missing") or "").strip():
            rep.error("R3", "%s 判定为「资料不足」但未填写 missing（缺什么）" % rid)

    # R4 硬门槛 FAIL 必须导致出局结论
    hard_fail = [r["id"] for r in reqs
                 if r.get("is_hard_gate") and items.get(r["id"], {}).get("status") == "FAIL"]
    if hard_fail and ev.get("conclusion") != "DISQUALIFIED":
        rep.error("R4", "存在硬门槛不满足 %s，但结论是 %s" % (hard_fail, ev.get("conclusion")))
    if not hard_fail and ev.get("conclusion") == "DISQUALIFIED":
        rep.error("R4", "结论为出局，但没有任何硬门槛被判不满足")

    # R5 分值池闭合
    model = rq.get("score_model", {}) or {}
    for pool in model.get("pools", []):
        c, per, tot = pool.get("declared_count"), num(pool.get("per_item")), num(pool.get("declared_total"))
        if c is not None and per is not None and tot is not None:
            calc = c * per
            if abs(calc - tot) > 0.011:
                rep.error("R5", "分值池 %s 不闭合: %d×%s=%s ≠ 声明 %s"
                          % (pool.get("symbol"), c, per, calc, tot))
        # 实际登记的条数（只数标准线「扣分项」；资质线/符合性线不进分值池）
        # 注意：标准线里有一类「加分项」（有 max_score、无 severity_symbol），
        # 它们按得分计、不按扣分计，绝不能混进「未标注符号」扣分池，否则条数永远对不上。
        sym = pool.get("symbol")
        actual = sum(1 for r in reqs
                     if r.get("line") == "SCORING"
                     and r.get("severity_symbol") == sym
                     and (sym is not None or num(r.get("max_score")) is None))
        if c is not None and actual != c:
            rep.warn("R5", "符号 %s：原文声明 %d 条，实际登记 %d 条 —— 需逐行核对（可能是原文引用多个符号的同句）"
                     % (sym, c, actual))

    # R6 单项扣分必须有分值池声明支撑
    declared = {(p.get("symbol"), num(p.get("per_item"))) for p in model.get("pools", [])}
    for r in reqs:
        per = num(r.get("per_item"))
        if per is not None and (r.get("severity_symbol"), per) not in declared:
            rep.error("R6", "%s 填了单条扣分 %s，但分值池里没有对应声明（不许自行估分）" % (r["id"], per))

    # R7 得分区间不越界
    tot = num(model.get("detail_total"))
    sr = ev.get("detail_score_range", {}) or {}
    lo, hi = num(sr.get("low")), num(sr.get("high"))
    if tot is not None:
        for name, v in (("下限", lo), ("上限", hi)):
            if v is not None and (v < -0.011 or v > tot + 0.011):
                rep.error("R7", "详细评审得分%s %.2f 越界（应落在 0~%.2f）" % (name, v, tot))
        if lo is not None and hi is not None and lo > hi + 0.011:
            rep.error("R7", "得分区间上下限颠倒: %.2f > %.2f" % (lo, hi))

    # R13 总分闭合：扣分池合计 + 加分项满分合计 必须等于详细评审总分
    # 对不上就说明「有分数没被拆成要求」或「池抄错了」，两者都是交付级错误。
    # 注意：pools 为空（纯加分制的招标）时也要平账 —— 早期版本在这里直接跳过，
    # 导致「一份只拆了加分项、扣分条款全漏」的清单照样过校验。
    pools_sum = sum(num(p.get("declared_total")) or 0.0 for p in model.get("pools", []))
    add_sum = sum(num(r.get("max_score")) or 0.0
                  for r in reqs if r.get("line") == "SCORING" and num(r.get("max_score")) is not None)
    if tot is not None:
        gap = tot - (pools_sum + add_sum)
        if abs(gap) > 0.011:
            rep.error("R13", "详细评审总分对不上：扣分池 %.2f + 加分项 %.2f = %.2f，但声明总分 %.2f（差 %.2f 分）"
                      % (pools_sum, add_sum, pools_sum + add_sum, tot, gap))

    # ---------- R14–R16：針對「判定值与分数不一致」的红队补丁 ----------
    # 背景写在 scripts/pentest.py：以下四组组合在原版本里全部静默通过。
    req_by_id = {r["id"]: r for r in reqs}

    # R14 判定值与计数/得分必须自洽（不许「判不符合却不扣分」「判不符合却得分」）
    for rid, it in items.items():
        r = req_by_id.get(rid, {})
        st = it.get("status")
        per = num(r.get("per_item"))
        mx = num(r.get("max_score"))
        aw = num(it.get("awarded"))
        fi = it.get("fail_items")
        ui = it.get("unknown_items")
        if st == "FAIL":
            if per is not None and r.get("line") == "SCORING" and fi is not None \
               and as_i(fi) < 1:
                rep.error("R14", "%s 判定为「不符合」但 fail_items=%s —— 会算出 0 扣分（必须 ≥1）"
                          % (rid, fi))
            if ui is not None and as_i(ui) > 0:
                rep.error("R14", "%s 判定为「不符合」（结论已确定）却填了 unknown_items=%s —— "
                                 "确定的结论不该再计资料不足项，否则最差口径被虚增扣分" % (rid, ui))
            if mx is not None and aw is not None and aw > 0.011:
                rep.error("R14", "%s 判定为「不符合」却填了得分 %s —— 不符合不得分" % (rid, aw))
        if st == "PASS":
            if per is not None and fi is not None and as_i(fi) > 0:
                rep.error("R14", "%s 判定为「符合」却填了 fail_items=%s" % (rid, fi))
            if mx is not None and aw is None:
                rep.error("R14", "%s 判定为「符合」且该项目有满分 %.2f，但未填 awarded（会记 0 分）"
                          % (rid, mx))
        if st == "NA":
            if (fi is not None and as_i(fi) > 0) or (ui is not None and as_i(ui) > 0):
                rep.error("R14", "%s 判定为「不适用」却填了 fail/unknown 项数" % rid)
            if aw is not None and aw > 0.011:
                rep.error("R14", "%s 判定为「不适用」却填了得分 %s" % (rid, aw))
        if (fi is not None and as_i(fi) < 0) or (ui is not None and as_i(ui) < 0):
            rep.error("R14", "%s 的 fail_items/unknown_items 为负数" % rid)

    # R15 得分不得超过该项满分、不得为负
    for rid, it in items.items():
        mx = num(req_by_id.get(rid, {}).get("max_score"))
        aw = num(it.get("awarded"))
        if mx is None or aw is None:
            continue
        if aw < -0.011:
            rep.error("R15", "%s 得分 %s 为负数" % (rid, aw))
        elif aw > mx + 0.011:
            rep.error("R15", "%s 得分 %s 超过该项满分 %s（超发 %.2f 分）"
                      % (rid, aw, mx, aw - mx))

    # R16 ★ 必须标硬门槛。漏标会让「出局」静默降级成「待定/通过」而不报任何错。
    for r in reqs:
        if r.get("severity_symbol") == "★" and not r.get("is_hard_gate"):
            rep.error("R16", "%s 带 ★ 符号但未标 is_hard_gate=true —— 它不满足时不会触发出局，结论会被静默降级"
                      % r["id"])
        # 反向：标了硬门槛却不在资质/符合性线，通常意味着线的归属填错了
        if r.get("is_hard_gate") and r.get("line") == "SCORING":
            rep.warn("R16", "%s 标了硬门槛却在标准线 —— 标准线一般是扣分不是出局，请确认"
                     % r["id"])

    # R17 各线条款总数平账（防止「整条线漏拆」：符号台账与分值闭合都管不到不计分的条款）
    declared_totals = rq.get("line_totals") or {}
    for ln in ("QUALIFICATION", "CONFORMITY", "SCORING"):
        d = declared_totals.get(ln)
        if d is None:
            continue
        actual_n = sum(1 for r in reqs if r.get("line") == ln)
        if actual_n != d:
            rep.error("R17", "%s 原文应有 %d 条，实际登记 %d 条（差 %d）—— 漏拆或拆重"
                      % (ln, d, actual_n, abs(d - actual_n)))
    if not declared_totals:
        rep.warn("R17", "未在 requirements.json 声明 line_totals（各线原文条款总数），"
                        "整条线漏拆将无机器校验 —— 请在拆条时人工数出并补上")

    # R8 / R11 / R12 证据链
    prof = load(a.profile) if (a.profile and os.path.exists(a.profile)) else None
    if prof is None:
        rep.warn("R8", "未提供 company_profile.json，跳过证据溯源校验（R8/R11/R12 全部跳过）")
    else:
        # R8 证据编号必须可追溯
        ev_ids = {e.get("id") for e in prof.get("evidence_index", [])}
        for rid, it in items.items():
            for e in it.get("evidence", []) or []:
                if e not in ev_ids:
                    rep.error("R8", "%s 引用了资料库里不存在的证据编号 %s" % (rid, e))

        # R11 证据来源标注完整：source 三选一；来自企查查的必须带 tool 与 fetched_at
        for e in prof.get("evidence_index", []):
            eid, src = e.get("id"), e.get("source")
            if src not in ("QCC", "WEB", "USER"):
                rep.error("R11", "证据 %s 的 source 缺失或非法: %r（应为 QCC/WEB/USER）" % (eid, src))
                continue
            if src == "QCC":
                if not (e.get("tool") or "").strip():
                    rep.error("R11", "证据 %s 来自企查查但未填 tool（用的是哪个接口）" % eid)
                if not (e.get("fetched_at") or "").strip():
                    rep.error("R11", "证据 %s 来自企查查但未填 fetched_at（什么时候查的）" % eid)
            if not (e.get("key_facts") or "").strip():
                rep.warn("R11", "证据 %s 未填 key_facts（这条证据到底证明了什么）" % eid)

        # R12 判"符合"必须挂证据，不许空口判 PASS
        for rid, it in items.items():
            if it.get("status") == "PASS" and not (it.get("evidence") or []):
                rep.error("R12", "%s 判为「符合」但没有任何证据编号 —— 属于幻觉" % rid)

    # R9 覆盖台账：源里每个符号位置都要登记处置
    fps = {}
    for p in glob.glob(os.path.join(W, "source_fingerprint.*.json")):
        fps[os.path.basename(p)] = load(p)
    # 键必须是 (符号, 行号)：同一行可能同时出现多个符号（如评分规则描述句同时含 ★▲█●）
    ledger = {(r.get("symbol"), r.get("line")): r for r in rq.get("coverage_ledger", [])}
    for fname, fp in fps.items():
        for sym, info in (fp.get("symbol_ledger") or {}).items():
            for ln in info.get("lines", []):
                rec = ledger.get((sym, ln))
                if rec is None:
                    rep.error("R9", "%s 第 %d 行的符号 %s 未在 coverage_ledger 登记"
                              % (fname, ln, sym))
                elif rec.get("disposition") == "EXEMPT" and not (rec.get("reason") or "").strip():
                    rep.error("R9", "第 %d 行的符号 %s 登记为 EXEMPT 但未写理由" % (ln, sym))
                elif rec.get("disposition") not in ("COVERED", "EXEMPT"):
                    rep.error("R9", "第 %d 行的符号 %s disposition 非法: %r"
                              % (ln, sym, rec.get("disposition")))

    # R10 原文溯源：quote 必须能在 raw 里找到
    raws = {}
    for p in glob.glob(os.path.join(W, "tender_raw.*.txt")):
        with io.open(p, "r", encoding="utf-8") as f:
            raws[os.path.basename(p)] = [l.strip() for l in f.read().splitlines()]
    if not raws:
        rep.warn("R10", "work/ 下没有 tender_raw.*.txt，跳过原文溯源校验")
    else:
        for r in reqs:
            q = (r.get("quote") or "").strip()
            if not q:
                rep.error("R10", "%s 没有原文引句 quote，无法溯源" % r["id"])
                continue
            needle = q[:30]
            hit_global = any(needle in l for lines in raws.values() for l in lines)
            if not hit_global:
                rep.error("R10", "%s 的原文引句在抽取文本里找不到: %r" % (r["id"], needle))
                continue
            lns = r.get("source_lines") or []
            if lns:
                hit_local = False
                for lines in raws.values():
                    for ln in lns:
                        window = lines[max(0, ln - 3): ln + 2]
                        if any(needle in l for l in window):
                            hit_local = True
                            break
                    if hit_local:
                        break
                if not hit_local:
                    rep.warn("R10", "%s 的引句在别处找到，但不在声明的行号 %s 附近 —— 行号需人工校正"
                             % (r["id"], lns))

    dump(rep)
    return 1 if rep.n_error else 0


def dump(rep):
    if rep.rows:
        for lv, rule, msg in rep.rows:
            print("[%s] %s %s" % (lv, rule, msg))
    print("---- 校验结果: %d ERROR / %d WARN ----" % (rep.n_error, rep.n_warn))


if __name__ == "__main__":
    sys.exit(main())
