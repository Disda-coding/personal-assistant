#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""search_memory.py 单元测试：切块、分词、加权、端到端检索。"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import search_memory as sm


class TestSplitFile(unittest.TestCase):
    """split_file: md 文件切块逻辑。"""

    def test_notes_style_each_heading_one_segment(self):
        """notes 结构: 每个条目(## 标题)一个片段, H1 作为文件级上下文。"""
        path = "/fake/notes/work.md"
        text = "# 工作\n\n## 2026-08-20 年报会议\n- 讨论海外扩张\n\n标签: #年报 #会议\n\n## 2026-08-25 周会\n- 同步进度\n"
        segs = sm.split_file(path, text)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["title"], "2026-08-20 年报会议")
        self.assertEqual(segs[0]["h1"], "工作")
        self.assertIn("标签: #年报 #会议", segs[0]["content"])
        self.assertEqual(segs[1]["title"], "2026-08-25 周会")

    def test_leading_metadata_becomes_segment(self):
        """summaries 结构(H1 修复): 首个 ## 前的元数据块(含 标签: 行)单独成块, 不再丢失。"""
        path = "/fake/summaries/2026-08-28_年报.docx.md"
        text = (
            "# 总结: 年报\n\n- 源文件: /tmp/x.docx\n- 日期: 2026-08-28\n"
            "- 分类: 工作\n- 标签: #量子财务审计\n\n## 核心内容\n- 营收增长\n"
        )
        segs = sm.split_file(path, text)
        self.assertEqual(len(segs), 2)
        head = segs[0]
        self.assertEqual(head["title"], "总结: 年报")
        self.assertIn("标签: #量子财务审计", head["content"])
        self.assertEqual(head["h1"], "总结: 年报")
        self.assertEqual(segs[1]["title"], "核心内容")

    def test_tasks_table_each_section_one_segment(self):
        """tasks.md: 每个 ## 分区一个片段(整表), 与文档 3.5 的表述一致。"""
        path = "/fake/tasks.md"
        text = (
            "# 我的任务\n\n## 进行中\n| ID | 任务 |\n|----|------|\n"
            "| T001 | 年报 PPT |\n\n## 已完成\n| ID | 任务 |\n"
        )
        segs = sm.split_file(path, text)
        self.assertEqual([s["title"] for s in segs], ["进行中", "已完成"])

    def test_no_heading_split_by_blank_line(self):
        """无标题文件: 按空行分段。"""
        segs = sm.split_file("/fake/plain.md", "第一段内容\n\n第二段内容\n")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["content"], "第一段内容")

    def test_empty_body_heading_skipped(self):
        """正文为空的 ## 标题不产生片段。"""
        text = "# H\n\n## 空标题\n\n## 有内容\n- 要点\n"
        segs = sm.split_file("/fake/x.md", text)
        self.assertEqual([s["title"] for s in segs], ["有内容"])

    def test_only_h1_no_body_no_segments(self):
        """仅 H1 无正文: 无孤立内容时不产生多余文件头片段。"""
        segs = sm.split_file("/fake/x.md", "# 标题\n\n## A\n- a\n")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["title"], "A")


class TestTokenize(unittest.TestCase):
    """tokenize: 中英混合分词。"""

    def test_chinese_bigram(self):
        """中文按字符二元组切分。"""
        self.assertEqual(sm.tokenize("年报会议"), ["年报", "报会", "会议"])

    def test_single_chinese_char(self):
        """单字中文直接保留。"""
        self.assertEqual(sm.tokenize("钱"), ["钱"])

    def test_english_lowercase_word(self):
        """英文/数字按小写单词。"""
        self.assertEqual(sm.tokenize("T001 Report"), ["t001", "report"])

    def test_mixed(self):
        """中英混合。"""
        tokens = sm.tokenize("T001 年报")
        self.assertEqual(tokens, ["t001", "年报"])


class TestSegmentTf(unittest.TestCase):
    """segment_tf: 标签行/标题加权。"""

    def test_tag_line_boosted_3x(self):
        """标签行权重 x3 (TAG_BOOST=3.0)。"""
        seg = {"content": "正文出现预算\n标签: #预算", "title": "", "h1": ""}
        tf = sm.segment_tf(seg)
        self.assertEqual(tf["预算"], 1.0 + 3.0)

    def test_bulleted_tag_line_boosted_3x(self):
        """P1 回归: 总结模板的 '- 标签: #x'(带项目符号)同样享受 x3 加权。"""
        seg = {"content": "正文出现预算\n- 标签: #预算", "title": "", "h1": ""}
        tf = sm.segment_tf(seg)
        self.assertEqual(tf["预算"], 1.0 + 3.0)

    def test_title_boosted_2x(self):
        """标题命中权重 x2 (TITLE_BOOST=2.0)。"""
        seg = {"content": "正文出现预算一次", "title": "预算会议", "h1": ""}
        tf = sm.segment_tf(seg)
        self.assertEqual(tf["预算"], 1.0 + 2.0)

    def test_h1_boosted_1x(self):
        """H1 文件级上下文权重 x1。"""
        seg = {"content": "", "title": "", "h1": "工作"}
        tf = sm.segment_tf(seg)
        self.assertEqual(tf["工作"], 1.0)


class TestReadText(unittest.TestCase):
    """read_text: 多编码回退。"""

    def test_gbk_fallback(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="gbk") as f:
            f.write("中文内容测试")
            path = f.name
        try:
            self.assertEqual(sm.read_text(path), "中文内容测试")
        finally:
            os.unlink(path)

    def test_utf8_sig(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as f:
            f.write("\ufeff带BOM内容".encode("utf-8"))
            path = f.name
        try:
            self.assertEqual(sm.read_text(path), "带BOM内容")
        finally:
            os.unlink(path)


class TestSearchEndToEnd(unittest.TestCase):
    """main() 端到端: 临时数据目录 + 捕获 stdout。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        os.makedirs(os.path.join(self.dir, "summaries"))
        with open(os.path.join(self.dir, "summaries", "2026-08-28_年报.docx.md"), "w", encoding="utf-8") as f:
            f.write(
                "# 总结: 年报\n\n- 源文件: /tmp/x.docx\n- 日期: 2026-08-28\n"
                "- 分类: 工作\n- 标签: #量子财务审计\n相关任务: T002 年报审核\n\n## 核心内容\n- 营收增长百分之二十\n"
            )
        os.makedirs(os.path.join(self.dir, "notes"))
        with open(os.path.join(self.dir, "notes", "work.md"), "w", encoding="utf-8") as f:
            f.write("# 工作\n\n## 2026-08-20 年报会议\n- 海外扩张计划\n\n标签: #年报 #会议\n\n相关任务: T001 年报PPT\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, query):
        out = io.StringIO()
        argv = ["search_memory.py", query, "--top", "5", "--dir", self.dir]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(out):
            rc = sm.main()
        return rc, out.getvalue()

    def test_search_tag_word_hits_metadata_segment(self):
        """H1 修复回归: 搜标签词能命中总结文件元数据块(修复前为'无匹配')。"""
        rc, out = self._run("量子财务审计")
        self.assertEqual(rc, 0)
        self.assertIn("标签: #量子财务审计", out)
        self.assertNotIn("无匹配", out)

    def test_search_body_text(self):
        """搜正文关键词命中 notes 条目并标注来源文件。"""
        rc, out = self._run("海外扩张")
        self.assertEqual(rc, 0)
        self.assertIn("海外扩张计划", out)
        self.assertIn("work.md", out)

    def test_search_task_id_hits_related_line(self):
        """3.5 反查路径依据: 任务 ID T001 可命中记忆侧'相关任务:'行。"""
        rc, out = self._run("T001")
        self.assertEqual(rc, 0)
        self.assertIn("相关任务: T001 年报PPT", out)

    def test_search_task_id_hits_summary_related_line(self):
        """P0 回归: 总结文件的'相关任务:'行(位于 ## 之前的元数据块)可被任务 ID 搜到。"""
        rc, out = self._run("T002")
        self.assertEqual(rc, 0)
        self.assertIn("相关任务: T002 年报审核", out)

    def test_search_no_match(self):
        """无结果时明确输出'无匹配'且退出码 0。"""
        rc, out = self._run("完全不存在的关键词xyz")
        self.assertEqual(rc, 0)
        self.assertIn("无匹配", out)

    def test_search_missing_dir(self):
        """数据目录不存在: 退出码 1 + 提示。"""
        out = io.StringIO()
        argv = ["search_memory.py", "任意", "--dir", os.path.join(self.dir, "nope")]
        with mock.patch("sys.argv", argv), contextlib.redirect_stdout(out):
            rc = sm.main()
        self.assertEqual(rc, 1)
        self.assertIn("数据目录不存在", out.getvalue())


if __name__ == "__main__":
    unittest.main()
