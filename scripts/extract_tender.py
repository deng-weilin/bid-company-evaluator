#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从招标/磋商文件（.docx 或 .pdf）抽取纯文本，产出可逐行溯源的工作底稿。

零第三方依赖：docx 走 zipfile+正则；pdf 走可用解析器或外部命令行，都不可用时明确 SKIP。

用法:
    python extract_tender.py <file1> [file2 ...] [--out DIR] [--tag TAG]

产出（写入 --out，默认 ./work）:
    tender_raw.<tag>.txt        按行排列的纯文本，行号即后续 locator
    source_fingerprint.<tag>.json  文件指纹、章节骨架、符号逐行台账
"""

import sys, os, io, re, json, zipfile, hashlib, subprocess, shutil

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = ["★", "▲", "█", "●", "◆", "○"]
PDF_TEXT_HINT = ["以pdf", "以PDF", "PDF格式内容为准", "pdf格式为准"]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))


def extract_docx(path):
    """纯标准库解析 docx：段落/表格均摊平成行。"""
    z = zipfile.ZipFile(path)
    target = "word/document.xml"
    if target not in z.namelist():
        raise RuntimeError("docx 内未找到 word/document.xml")
    xml = z.read(target).decode("utf-8", "ignore")

    xml = xml.replace("</w:p>", "\x01")
    xml = xml.replace("</w:tr>", "\x01")
    xml = xml.replace("</w:tc>", "\x02")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", " ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = unescape(text)

    lines = []
    for para in text.split("\x01"):
        para = " ".join(c.strip() for c in para.split("\x02") if c.strip())
        para = re.sub(r"[ \t]+", " ", para).strip()
        if para:
            lines.append(para)
    return lines, "docx(zipfile)"


def _try_pdf_libs(path):
    for mod, fn in (("pypdf", "PdfReader"), ("PyPDF2", "PdfReader"), ("pdfplumber", "open")):
        try:
            m = __import__(mod)
        except Exception:
            continue
        try:
            if mod == "pdfplumber":
                with m.open(path) as pdf:
                    pages = [(p.extract_text() or "") for p in pdf.pages]
            else:
                rd = getattr(m, fn)(path)
                pages = [(p.extract_text() or "") for p in rd.pages]
            return pages, mod
        except Exception:
            continue
    return None, None


def _try_pdf_bins(path):
    for exe in ("pdftotext", "mutool"):
        if not shutil.which(exe):
            continue
        try:
            if exe == "pdftotext":
                out = subprocess.run([exe, "-enc", "UTF-8", "-layout", path, "-"],
                                     capture_output=True, timeout=180)
            else:
                out = subprocess.run([exe, "draw", "-F", "txt", path],
                                     capture_output=True, timeout=180)
            if out.returncode == 0 and out.stdout:
                txt = out.stdout.decode("utf-8", "ignore")
                return txt.split("\f") if "\f" in txt else txt.splitlines(), exe
        except Exception:
            continue
    return None, None


def extract_pdf(path):
    pages, how = _try_pdf_libs(path)
    if pages is None:
        pages, how = _try_pdf_bins(path)
    if pages is None:
        return None, None
    lines = []
    for p in pages:
        for ln in str(p).splitlines():
            ln = re.sub(r"[ \t]+", " ", ln).strip()
            if ln:
                lines.append(ln)
    return lines, how


SECTION_RE = re.compile(
    r"^(第[一二三四五六七八九十]+章|第[一二三四五六七八九十]+节"
    r"|[一二三四五六七八九十]+、|\d+(?:\.\d+){1,3}(?:[ 、])?)\s*\S*")


def build_skeleton(lines):
    skel = []
    for i, ln in enumerate(lines, 1):
        if len(ln) > 60:
            continue
        m = SECTION_RE.match(ln)
        if m:
            skel.append({"line": i, "text": ln[:60]})
    return skel


def build_symbol_ledger(lines):
    """逐行登记每个严重度符号出现的位置——覆盖台账的数据源。"""
    ledger = {}
    for sym in SYMBOLS:
        hits = [{"line": i, "context": ln[:80]}
                for i, ln in enumerate(lines, 1) if sym in ln]
        if hits:
            ledger[sym] = {"count": len(hits), "lines": [h["line"] for h in hits],
                           "detail": hits}
    return ledger


def detect_pdf_priority(lines):
    hits = []
    for i, ln in enumerate(lines, 1):
        if any(k in ln for k in PDF_TEXT_HINT):
            hits.append({"line": i, "text": ln[:120]})
    return hits


def main():
    out = "./work"
    tag = None
    args = []
    i = 1
    while i < len(sys.argv):
        cur = sys.argv[i]
        if cur == "--out" and i + 1 < len(sys.argv):
            out = sys.argv[i + 1]; i += 2; continue
        if cur == "--tag" and i + 1 < len(sys.argv):
            tag = sys.argv[i + 1]; i += 2; continue
        if cur.startswith("--"):
            print("[警告] 忽略未知参数: %s" % cur); i += 1; continue
        args.append(cur); i += 1

    if not args:
        print("用法: python extract_tender.py <file1> [file2 ...] [--out DIR] [--tag TAG]")
        return 2
    os.makedirs(out, exist_ok=True)

    summary = []
    for path in args:
        ext = os.path.splitext(path)[1].lower()
        tag_here = tag or re.sub(r"\W+", "_", os.path.splitext(os.path.basename(path))[0])[:40]
        lines, how = (None, None)
        if ext == ".docx":
            lines, how = extract_docx(path)
        elif ext == ".pdf":
            lines, how = extract_pdf(path)
        else:
            print("[跳过] 不支持的扩展名: %s" % path)
            summary.append({"file": path, "status": "SKIPPED", "reason": "unsupported ext"})
            continue

        if lines is None:
            print("[跳过] %s 无法抽取文本。请用 Read 工具直接读取 PDF，"
                  "或安装 pypdf/pdfplumber/pdftotext 后重跑。" % path)
            summary.append({"file": path, "status": "SKIPPED",
                            "reason": "no pdf extractor available", "tag": tag_here})
            continue

        raw = os.path.join(out, "tender_raw.%s.txt" % tag_here)
        with io.open(raw, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        fp = {
            "file": os.path.abspath(path),
            "tag": tag_here,
            "sha256": sha256_of(path),
            "size_bytes": os.path.getsize(path),
            "chars": sum(len(l) for l in lines),
            "lines": len(lines),
            "extractor": how,
            "raw_file": os.path.basename(raw),
            "sections": build_skeleton(lines),
            "symbol_ledger": build_symbol_ledger(lines),
            "pdf_priority_hints": detect_pdf_priority(lines),
        }
        fp_path = os.path.join(out, "source_fingerprint.%s.json" % tag_here)
        with io.open(fp_path, "w", encoding="utf-8") as f:
            json.dump(fp, f, ensure_ascii=False, indent=2)

        sym = {k: v["count"] for k, v in fp["symbol_ledger"].items()}
        print("[OK] %s -> %s (%d 行, %s) 符号统计=%s" %
              (os.path.basename(path), raw, len(lines), how, sym or "无"))
        if fp["pdf_priority_hints"]:
            print("     !! 检出「以 PDF 为准」类声明，行号: %s —— 必须比对两个版本"
                  % [h["line"] for h in fp["pdf_priority_hints"]])
        summary.append({"file": path, "tag": tag_here, "status": "OK",
                        "lines": len(lines), "extractor": how,
                        "symbol_counts": sym})

    idx = os.path.join(out, "extract_index.json")
    with io.open(idx, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("索引: %s" % idx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
