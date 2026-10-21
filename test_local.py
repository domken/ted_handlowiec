"""Lokalne testy parsera i eksportu XLSX, bez połączenia z siecią."""
from pathlib import Path
import os
import sys
import unittest
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

os.environ.setdefault("TED_HANDLOWIEC_DATA", "/private/tmp/ted_handlowiec_test_data")
sys.path.insert(0, str(Path(__file__).parent))
import app


class NoticeParserTests(unittest.TestCase):
    def test_parse_real_ted_xml(self):
        files = sorted((Path(__file__).parent.parent / "TED_IT_Polska").glob("*.xml"))
        self.assertTrue(files, "Oczekiwano lokalnych XML-i TED do testu.")
        file = files[0]
        result = app.parse_xml(file.read_bytes(), file.stem)
        self.assertEqual(result["number"], file.stem)
        self.assertTrue(result["title"])
        self.assertTrue(result["buyer"])
        self.assertIsInstance(result["lots"], list)

    def test_xlsx_is_valid_zip_and_contains_xml(self):
        files = sorted((Path(__file__).parent.parent / "TED_IT_Polska").glob("*.xml"))
        file = files[0]
        notice = app.parse_xml(file.read_bytes(), file.stem)
        raw = app.make_xlsx(notice)
        with zipfile.ZipFile(BytesIO(raw)) as package:
            self.assertIn("xl/workbook.xml", package.namelist())
            self.assertIn("xl/worksheets/sheet1.xml", package.namelist())
            self.assertIn("xl/worksheets/sheet2.xml", package.namelist())
            self.assertIn("xl/worksheets/sheet3.xml", package.namelist())
            workbook = ET.fromstring(package.read("xl/workbook.xml"))
            self.assertEqual([node.attrib["name"] for node in workbook.iter() if node.tag.endswith("}sheet")],
                             ["Lista", "Szczegóły", "Części"])
            details = ET.fromstring(package.read("xl/worksheets/sheet2.xml"))
            self.assertTrue(any((node.text or "") == "Opis zamówienia" for node in details.iter()))

    def test_api_fields_normalization(self):
        notice = app.norm_notice({
            "publication-number": "123456-2026",
            "notice-title": {"pol": ["Tytuł testowy"]},
            "buyer-name": {"pol": ["Zamawiający"]},
            "classification-cpv": ["72000000", "72260000"],
        })
        self.assertEqual(notice["title"], "Tytuł testowy")
        self.assertEqual(notice["buyer"], "Zamawiający")
        self.assertEqual(notice["cpv"], "72000000, 72260000")


if __name__ == "__main__":
    unittest.main()
