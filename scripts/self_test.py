#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自检：用内置样例跑通 evaluate + validate，并验证规则确实会拦。

用法: python self_test.py
返回码: 0 = 全部通过; 1 = 有断言失败
"""

import sys, os, io, json, tempfile, shutil, subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = [
    "竞争性磋商文件",
    "★供应商报价不得超过最高限价 650000 元。",
    "▲系统支持能力图谱建设，提供功能截图。",
    "●要求现场演示虚拟仿真资源联动。",
    "供应商具有虚拟仿真相关软件著作权证书每有一个得0.25分，最多得7分。",
    "供应商自2023年1月1日承担过类似项目业绩，每提供1个得1分，最高得5分。",
]

GOOD_REQ = {
    "tender": {"name": "自检样例项目", "code": "TEST-001", "buyer": "某采购人",
               "raw_file": "tender_raw.self.txt", "ceiling": 650000},
    "score_model": {
        # 闭合：扣分池 1.5+0.5=2.0 ；加分项 7.0+5.0=12.0 ；合计 14.0 = detail_total
        "detail_total": 14.0, "price_total": 10.0,
        "pools": [
            {"symbol": "▲", "declared_count": 1, "per_item": 1.5,
             "declared_total": 1.5, "source_line": 3},
            {"symbol": "●", "declared_count": 1, "per_item": 0.5,
             "declared_total": 0.5, "source_line": 4},
        ],
    },
    "requirements": [
        {"id": "REQ-001", "line": "QUALIFICATION", "category": "政策资格",
         "title": "专门面向中小企业", "text": "专门面向中小企业采购",
         "severity_symbol": None, "is_hard_gate": True, "per_item": None,
         "max_score": None, "source_lines": [1], "quote": "竞争性磋商文件"},
        {"id": "REQ-002", "line": "CONFORMITY", "category": "商务实质性",
         "title": "报价不得超过最高限价", "text": "★供应商报价不得超过最高限价 650000 元。",
         "severity_symbol": "★", "is_hard_gate": True, "per_item": None,
         "max_score": None, "source_lines": [2], "quote": "★供应商报价不得超过最高限价"},
        {"id": "REQ-003", "line": "SCORING", "category": "技术评分",
         "title": "能力图谱", "text": "▲系统支持能力图谱建设",
         "severity_symbol": "▲", "is_hard_gate": False, "per_item": 1.5,
         "max_score": None, "source_lines": [3], "quote": "▲系统支持能力图谱建设"},
        {"id": "REQ-004", "line": "SCORING", "category": "技术评分",
         "title": "虚仿联动演示", "text": "●要求现场演示虚拟仿真资源联动。",
         "severity_symbol": "●", "is_hard_gate": False, "per_item": 0.5,
         "max_score": None, "source_lines": [4], "quote": "●要求现场演示虚拟仿真资源联动"},
        {"id": "REQ-005", "line": "SCORING", "category": "履约能力",
         "title": "软著证书", "text": "每有一个得0.25分，最多得7分",
         "severity_symbol": None, "is_hard_gate": False, "per_item": None,
         "max_score": 7.0, "source_lines": [5], "quote": "每有一个得0.25分"},
        {"id": "REQ-006", "line": "SCORING", "category": "类似业绩",
         "title": "业绩", "text": "每提供1个得1分，最高得5分",
         "severity_symbol": None, "is_hard_gate": False, "per_item": None,
         "max_score": 5.0, "source_lines": [6], "quote": "每提供1个得1分"},
    ],
    "coverage_ledger": [
        {"symbol": "★", "line": 2, "req_id": "REQ-002", "disposition": "COVERED"},
        {"symbol": "▲", "line": 3, "req_id": "REQ-003", "disposition": "COVERED"},
        {"symbol": "●", "line": 4, "req_id": "REQ-004", "disposition": "COVERED"},
    ],
    "issues": [],
}

GOOD_ASSESS = {
    "company": "自检样例有限公司",
    "items": [
        {"req_id": "REQ-001", "status": "PASS", "evidence": ["EV-001"], "note": ""},
        {"req_id": "REQ-002", "status": "PASS", "evidence": ["EV-002"], "note": ""},
        {"req_id": "REQ-003", "status": "FAIL", "fail_items": 1, "unknown_items": 0,
         "evidence": [], "note": "平台无能力图谱模块"},
        {"req_id": "REQ-004", "status": "UNKNOWN", "fail_items": 0, "unknown_items": 1,
         "missing": "未提供现场演示安排与截图", "note": ""},
        {"req_id": "REQ-005", "status": "PASS", "awarded": 2.0, "evidence": ["EV-003"], "note": "8个软著"},
        {"req_id": "REQ-006", "status": "PASS", "awarded": 3.0, "evidence": ["EV-004"], "note": "3个业绩"},
    ],
}

def ev(i, tool, facts):
    return {"id": "EV-%03d" % i, "name": tool, "source": "QCC", "tool": tool,
            "fetched_at": "2026-10-10", "key_facts": facts, "file": None, "note": None}


PROFILE = {
    "company": {"legal_name": "自检样例有限公司"},
    "qcc_entity": {"legal_name": "自检样例有限公司", "credit_code": "self-test-code",
                   "match_type": "唯一精确匹配", "fetched_at": "2026-10-10"},
    "evidence_index": [
        ev(1, "get_company_registration_info", "成立2020-01-01；参保18人；软件和信息技术服务业"),
        ev(2, "get_dishonest_info", "当前无失信被执行人记录"),
        ev(3, "get_software_copyright_info", "软著8项，逐个核对后与招标限定领域相关8项"),
        ev(4, "get_bidding_info", "2023年以来中标记录3条，去重后3个独立项目"),
    ],
}


def run_case(name, req, assess, profile, expect_errors_at_least):
    d = tempfile.mkdtemp(prefix="bce_selftest_")
    try:
        with io.open(os.path.join(d, "tender_raw.self.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(RAW) + "\n")
        fp = {"file": "self", "tag": "self", "symbol_ledger": {
            "★": {"count": 1, "lines": [2], "detail": [{"line": 2, "context": ""}]},
            "▲": {"count": 1, "lines": [3], "detail": [{"line": 3, "context": ""}]},
            "●": {"count": 1, "lines": [4], "detail": [{"line": 4, "context": ""}]},
        }}
        for fn, obj in (("requirements.json", req), ("assessments.json", assess),
                        ("source_fingerprint.self.json", fp),
                        ("company_profile.json", profile)):
            with io.open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)

        py = sys.executable
        ev = subprocess.run([py, os.path.join(HERE, "evaluate.py"),
                             "--requirements", os.path.join(d, "requirements.json"),
                             "--assessments", os.path.join(d, "assessments.json"),
                             "--profile", os.path.join(d, "company_profile.json"),
                             "--out", d], capture_output=True)
        if ev.returncode != 0:
            print("[FAIL] %s evaluate.py 退出码 %d\n%s" % (name, ev.returncode,
                                                          ev.stderr.decode("utf-8", "ignore")))
            return False
        va = subprocess.run([py, os.path.join(HERE, "validate.py"), "--work", d,
                             "--profile", os.path.join(d, "company_profile.json")],
                            capture_output=True)
        outp = va.stdout.decode("utf-8", "ignore")
        n_err = int(outp.rsplit("---- 校验结果: ", 1)[1].split(" ")[0]) if "校验结果" in outp else -1
        ok = n_err >= expect_errors_at_least
        print("[%s] %s -> ERROR=%d (期望 >=%d)" %
              ("PASS" if ok else "FAIL", name, n_err, expect_errors_at_least))
        if not ok:
            print(outp)
        if name == "金样例" and ok:
            with io.open(os.path.join(d, "evaluation.json"), "r", encoding="utf-8") as f:
                res = json.load(f)
            lo, hi = res["detail_score_range"]["low"], res["detail_score_range"]["high"]
            # 扣分池基准 1.5+0.5=2.0（全满足即得）；加分 2.0+3.0=5.0
            # 下限: 2.0 + 5.0 - (1.5 fail + 0.5 unknown) = 5.0 ; 上限: 2.0 + 5.0 - 1.5 = 5.5
            if abs(lo - 5.0) > 0.011 or abs(hi - 5.5) > 0.011:
                print("[FAIL] 金样例得分区间算错: low=%s high=%s (期望 5.0 / 5.5)" % (lo, hi))
                return False
            print("       得分区间 %.2f~%.2f 正确；结论=%s" % (lo, hi, res["conclusion_name"]))
        return ok
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    ok = True
    ok &= run_case("金样例", GOOD_REQ, GOOD_ASSESS, PROFILE, 0)

    # 变异 1：硬门槛判 FAIL，却漏掉出局结论（靠 evaluate 自动推导，应仍为 DISQUALIFIED）
    r2 = json.loads(json.dumps(GOOD_REQ))
    a2 = json.loads(json.dumps(GOOD_ASSESS))
    a2["items"][0]["status"] = "FAIL"
    d = tempfile.mkdtemp(prefix="bce_mut1_")
    with io.open(os.path.join(d, "tender_raw.self.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(RAW) + "\n")
    for fn, obj in (("requirements.json", r2), ("assessments.json", a2)):
        with io.open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    subprocess.run([sys.executable, os.path.join(HERE, "evaluate.py"),
                    "--requirements", os.path.join(d, "requirements.json"),
                    "--assessments", os.path.join(d, "assessments.json"),
                    "--out", d], capture_output=True)
    with io.open(os.path.join(d, "evaluation.json"), "r", encoding="utf-8") as f:
        c = json.load(f)["conclusion"]
    good = c == "DISQUALIFIED"
    print("[%s] 变异1 硬门槛FAIL应自动出局 -> %s" % ("PASS" if good else "FAIL", c))
    ok &= good
    shutil.rmtree(d, ignore_errors=True)

    # 变异 2：UNKNOWN 不写 missing + 引句伪造 + 凭空扣分，validate 必须报错
    r3 = json.loads(json.dumps(GOOD_REQ))
    a3 = json.loads(json.dumps(GOOD_ASSESS))
    a3["items"][3].pop("missing", None)
    r3["requirements"][2]["quote"] = "这句话根本不在原文里"
    r3["requirements"][0]["per_item"] = 9.9
    ok &= run_case("变异2（应被拦截）", r3, a3, PROFILE, 3)

    # 变异 3：空口判 PASS（无证据）+ 企查查证据漏填 tool，R11/R12 必须拦
    a4 = json.loads(json.dumps(GOOD_ASSESS))
    a4["items"][0]["evidence"] = []
    p4 = json.loads(json.dumps(PROFILE))
    p4["evidence_index"][1].pop("tool", None)
    p4["evidence_index"][2]["source"] = "网上看到的"
    ok &= run_case("变异3（证据链应被拦截）", GOOD_REQ, a4, p4, 3)

    # 变异 4：总分对不上（扣分池+加分项 ≠ 声明总分），R13 必须拦
    r5 = json.loads(json.dumps(GOOD_REQ))
    r5["score_model"]["detail_total"] = 30.0
    ok &= run_case("变异4（总分不闭合应被拦截）", r5, GOOD_ASSESS, PROFILE, 1)

    # 变异 5：加分项漏填 max_score（7 分凭空消失），R13 总分闭合必须拦
    r6 = json.loads(json.dumps(GOOD_REQ))
    r6["score_model"]["pools"].append(
        {"symbol": None, "declared_count": 1, "per_item": 0.4,
         "declared_total": 0.4, "source_line": 3})
    r6["requirements"][4].pop("max_score", None)   # REQ-005 从加分项变成无符号项
    ok &= run_case("变异5（加分项漏填满分应被拦截）", r6, GOOD_ASSESS, PROFILE, 1)

    print("---- 自检 %s ----" % ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
