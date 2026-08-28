#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地记忆检索脚本（RAG 式召回，纯标准库，离线零依赖）。

用法:
    python search_memory.py "查询关键词" [--top 5] [--dir "<assistant 数据目录>"]

流程:
    递归扫描 .md 文件 → 按 ## 标题切块 → 中英混合分词（中文 bigram）
    → TF-IDF 式打分（标签行/标题加权）→ 输出 Top-N 片段（含文件路径与得分）
输出为结构化纯文本，供 AI 二次 Read 上下文后引用作答。
"""
import argparse
import math
import os
import re
import sys
from collections import Counter

TAG_LINE_RE = re.compile(r"^\s*(标签|tags?)\s*[:：]", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{2,6}\s+(.*)$")
H1_RE = re.compile(r"^#\s+(.*)$")
CN_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")

TAG_BOOST = 3.0    # 标签行命中加权
TITLE_BOOST = 2.0  # 标题命中加权
MAX_EXCERPT = 600  # 片段摘录最大字符数


def reconfigure_stdout():
    # 防止 Windows 控制台 GBK 乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def tokenize(text):
    """中英混合分词: 英文/数字按小写单词; 中文按字符二元组(bigram)。"""
    tokens = [w.lower() for w in WORD_RE.findall(text)]
    for seg in CN_RE.findall(text):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def read_text(path):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _para_seg(path, h1, para, pstart):
    return {
        "file": path,
        "h1": h1,
        "title": para[0].lstrip("#").strip()[:40] or "(片段)",
        "start": pstart + 1,
        "end": pstart + len(para),
        "content": "\n".join(para),
    }


def split_file(path, text):
    """把一个 md 文件切成片段列表。

    有 ## 级及以上标题: 每个标题一个片段（H1 作为文件级上下文）；
    首个 ## 之前的孤立内容（如总结文件的元数据块）也单独成一个片段。
    无标题: 按空行分段。
    """
    segs = []
    lines = text.splitlines()

    h1 = ""
    for line in lines:
        m = H1_RE.match(line)
        if m:
            h1 = m.group(1).strip()
            break

    heading_idx = [i for i, l in enumerate(lines) if HEADING_RE.match(l)]

    if heading_idx:
        # 首个 ## 之前的孤立内容（如总结文件的元数据块）单独成块，
        # 保证其中的 标签: 等元数据行也能被检索到（否则永远不进任何片段）
        head_start = next(
            (i for i, l in enumerate(lines[: heading_idx[0]])
             if l.strip() and not H1_RE.match(l)),
            None,
        )
        if head_start is not None:
            head = [l for l in lines[head_start : heading_idx[0]] if l.strip()]
            segs.append({
                "file": path,
                "h1": h1,
                "title": (h1 or "(文件头)")[:40],
                "start": head_start + 1,
                "end": heading_idx[0],
                "content": "\n".join(head),
            })
        bounds = heading_idx + [len(lines)]
        for k in range(len(heading_idx)):
            start = heading_idx[k]
            end = bounds[k + 1]
            title = HEADING_RE.match(lines[start]).group(1).strip() or "(无标题)"
            body = lines[start + 1 : end]
            if not any(l.strip() for l in body):
                continue
            segs.append({
                "file": path,
                "h1": h1,
                "title": title,
                "start": start + 1,
                "end": end,
                "content": "\n".join(body),
            })
    else:
        para, pstart = [], 0
        for i, line in enumerate(lines):
            if line.strip():
                if not para:
                    pstart = i
                para.append(line)
            elif para:
                segs.append(_para_seg(path, h1, para, pstart))
                para = []
        if para:
            segs.append(_para_seg(path, h1, para, pstart))
    return segs


def segment_tf(seg):
    """计算片段内 token 的加权词频: 标签行 x3, 标题 x2, 正文 x1。"""
    counts = Counter()
    for line in seg["content"].splitlines():
        if not line.strip():
            continue
        w = TAG_BOOST if TAG_LINE_RE.match(line) else 1.0
        for t in tokenize(line):
            counts[t] += w
    for t in tokenize(seg["title"]):
        counts[t] += TITLE_BOOST
    if seg["h1"]:
        for t in tokenize(seg["h1"]):
            counts[t] += 1.0
    return counts


def main():
    reconfigure_stdout()
    ap = argparse.ArgumentParser(description="本地记忆检索（RAG 召回）")
    ap.add_argument("query", help="查询关键词")
    ap.add_argument("--top", type=int, default=5, help="返回片段数（默认 5）")
    ap.add_argument(
        "--dir",
        default=os.path.join(os.path.expanduser("~"), "assistant"),
        help="记忆数据根目录（默认 ~/assistant）",
    )
    args = ap.parse_args()

    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print(f"错误: 数据目录不存在: {root}")
        print("提示: 首次使用请先初始化 ~/assistant 目录, 或用 --dir 指定路径。")
        return 1

    md_files = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(".md"):
                md_files.append(os.path.join(dirpath, fn))
    if not md_files:
        print(f"无匹配: {root} 下没有 .md 文件。")
        return 0

    segments = []
    for p in md_files:
        try:
            segments.extend(split_file(p, read_text(p)))
        except OSError:
            continue
    if not segments:
        print("无匹配: 记忆目录中没有可检索的内容片段。")
        return 0

    query_tokens = tokenize(args.query)
    if not query_tokens:
        print("无匹配: 查询词为空或无法分词。")
        return 0

    n = len(segments)
    # 文档频率（片段级）→ idf
    df = Counter()
    for seg in segments:
        seg["tokens"] = set(tokenize(seg["content"])) | set(tokenize(seg["title"]))
        if seg["h1"]:
            seg["tokens"] |= set(tokenize(seg["h1"]))
        for t in seg["tokens"]:
            df[t] += 1

    qcounter = Counter(query_tokens)
    scored = []
    for seg in segments:
        tf = segment_tf(seg)
        s = 0.0
        for t, qc in qcounter.items():
            if t in tf and t in df:
                idf = math.log((n + 1) / (df[t] + 1)) + 1
                s += qc * tf[t] * idf
        if s > 0:
            # 长度归一化, 避免长片段天然占优
            scored.append((s / math.sqrt(len(seg["tokens"]) + 1), seg))

    if not scored:
        print(f"无匹配: 已扫描 {len(md_files)} 个文件 / {n} 个片段, 未找到与“{args.query}”相关的内容。")
        return 0

    scored.sort(key=lambda x: (-x[0], x[1]["file"], x[1]["start"]))
    shown = min(args.top, len(scored))
    print(f"扫描: {len(md_files)} 个文件 / {n} 个片段; 命中 {len(scored)} 个, 显示前 {shown} 个")
    print()
    for rank, (score, seg) in enumerate(scored[:shown], 1):
        excerpt = seg["content"].strip()
        if len(excerpt) > MAX_EXCERPT:
            excerpt = excerpt[:MAX_EXCERPT] + "\n[...已截断, 完整内容请 Read 该文件]"
        title = seg["title"]
        if seg["h1"] and seg["h1"] != seg["title"]:
            title += f"  (所属文件: {seg['h1']})"
        print(f"=== 片段 {rank} | 得分 {score:.2f} ===")
        print(f"文件: {seg['file']}")
        print(f"标题: {title}")
        print(f"行号: L{seg['start']}-L{seg['end']}")
        print("内容:")
        print(excerpt)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
