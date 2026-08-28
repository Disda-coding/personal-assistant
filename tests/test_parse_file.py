#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_file.py 单元测试：XML 实体解码、二进制检测、降级解析路径。"""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import parse_file as pf


class TestXmlUnescape(unittest.TestCase):
    """xml_unescape: 命名实体 + 数字字符引用。"""

    def test_named_entities(self):
        self.assertEqual(pf.xml_unescape("&amp;&lt;&gt;&quot;&apos;"), "&<>\"'")

    def test_decimal_reference(self):
        self.assertEqual(pf.xml_unescape("&#65;&#66;"), "AB")

    def test_hex_reference(self):
        """十六进制引用(openpyxl sharedStrings 常用), 如 &#x4e2d; → 中。"""
        self.assertEqual(pf.xml_unescape("&#x4e2d;&#x6587;"), "中文")

    def test_unknown_entity_kept(self):
        """未知实体原样保留, 不崩溃。"""
        self.assertEqual(pf.xml_unescape("&unknown;"), "&unknown;")

    def test_invalid_numeric_no_crash(self):
        """非法数字引用(如超范围)不崩溃。"""
        out = pf.xml_unescape("&#999999999999;正常")
        self.assertIn("正常", out)


class TestIsBinary(unittest.TestCase):
    """is_binary: 前 1024 字节含 \\x00 判为二进制。"""

    def test_binary_detected(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"ab\x00cd")
            path = f.name
        try:
            self.assertTrue(pf.is_binary(path))
        finally:
            os.unlink(path)

    def test_text_not_binary(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write("纯文本".encode("utf-8"))
            path = f.name
        try:
            self.assertFalse(pf.is_binary(path))
        finally:
            os.unlink(path)


class TestDocxFallback(unittest.TestCase):
    """parse_docx_fallback: zipfile+正则 零依赖降级。"""

    def _make_docx(self, xml):
        f = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("word/document.xml", xml)
        f.close()
        return f.name

    def test_text_and_paragraph_break(self):
        """提取 <w:t> 文本, </w:p> 处断行。"""
        xml = "<w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:p><w:r><w:t>第二段</w:t></w:r></w:p>"
        path = self._make_docx(xml)
        try:
            text, method = pf.parse_docx_fallback(path)
            self.assertEqual(text, "第一段\n第二段")
            self.assertIn("降级", method)
        finally:
            os.unlink(path)

    def test_xml_entities_decoded(self):
        xml = "<w:p><w:r><w:t>A &amp; B</w:t></w:r></w:p>"
        path = self._make_docx(xml)
        try:
            text, _ = pf.parse_docx_fallback(path)
            self.assertEqual(text, "A & B")
        finally:
            os.unlink(path)


class TestXlsxFallback(unittest.TestCase):
    """parse_xlsx_fallback: sharedStrings + 单元格类型。"""

    def test_shared_string_and_inline(self):
        """t="s" 走共享字符串索引, 内联 <t> 直接取。"""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        with zipfile.ZipFile(f, "w") as z:
            z.writestr(
                "xl/sharedStrings.xml",
                '<sst><si><t>苹果</t></si><si><t>香蕉</t></si></sst>',
            )
            z.writestr(
                "xl/worksheets/sheet1.xml",
                '<sheetData>'
                '<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
                "<row><c><v>42</v></c><c><t>内联</t></c></row>"
                "</sheetData>",
            )
        f.close()
        try:
            text, method = pf.parse_xlsx_fallback(f.name)
            self.assertIn("苹果 | 香蕉", text)
            self.assertIn("42 | 内联", text)
            self.assertIn("降级", method)
        finally:
            os.unlink(f.name)

    def test_missing_shared_strings(self):
        """无 sharedStrings 时不崩溃, 仍读内联值。"""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", "<sheetData><row><c><v>7</v></c></row></sheetData>")
        f.close()
        try:
            text, _ = pf.parse_xlsx_fallback(f.name)
            self.assertIn("7", text)
        finally:
            os.unlink(f.name)


class TestParsePptx(unittest.TestCase):
    """parse_pptx: zipfile+正则 零依赖。"""

    def test_slides_sorted_and_extracted(self):
        """slide 按数字顺序提取文本(10 与 2 不乱序)。"""
        f = tempfile.NamedTemporaryFile(suffix=".pptx", delete=False)
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("ppt/slides/slide2.xml", "<a:t>第二页</a:t>")
            z.writestr("ppt/slides/slide10.xml", "<a:t>第十页</a:t>")
            z.writestr("ppt/slides/slide1.xml", "<a:t>第一页</a:t>")
        f.close()
        try:
            text, _ = pf.parse_pptx(f.name)
            self.assertEqual(text, "--- 幻灯片 1 ---\n第一页\n--- 幻灯片 2 ---\n第二页\n--- 幻灯片 3 ---\n第十页")
        finally:
            os.unlink(f.name)


class TestReadTextFile(unittest.TestCase):
    """read_text_file: 编码回退。"""

    def test_gbk(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write("中文测试".encode("gbk"))
            path = f.name
        try:
            self.assertEqual(pf.read_text_file(path), "中文测试")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
