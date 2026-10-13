"""合成报告验证：缺失依赖/失败报告不能通过质量门。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend_quality import ALLOWED_SKIPS, audit_report


class ReportAuditTests(unittest.TestCase):
    def audit(self, body):
        with TemporaryDirectory() as directory:
            report = Path(directory) / "result.xml"
            report.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>", encoding="utf-8")
            return audit_report(report)

    def test_success_and_declared_resource_skip(self):
        classname, name = sorted(ALLOWED_SKIPS)[0]
        self.assertEqual(self.audit(
            '<testcase classname="synthetic" name="passing" />'
            f'<testcase classname="{classname}" name="{name}"><skipped /></testcase>'
        ), (1, 1))

    def test_missing_console_dependency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未经声明"):
            self.audit('<testcase classname="tests.unit.entrypoints.test_console" name="test_console"><skipped message="aiohttp missing" /></testcase>')

    def test_failure_and_collection_error_are_rejected(self):
        for kind in ("failure", "error"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "含失败"):
                self.audit(f'<testcase classname="synthetic" name="failed"><{kind} /></testcase>')

    def test_empty_report_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "没有测试"):
            self.audit("")

    def test_config_symlink_skip_requires_declared_permission_reason(self):
        classname = "tests.unit.development.test_local_config_layout"
        name = "test_migration_rejects_escape_and_symlink"
        prefix = '<testcase classname="synthetic" name="passing" />'
        with self.assertRaisesRegex(ValueError, "原因与声明不符"):
            self.audit(prefix + f'<testcase classname="{classname}" name="{name}"><skipped message="unexpected failure" /></testcase>')
        self.assertEqual(self.audit(prefix + f'<testcase classname="{classname}" name="{name}"><skipped message="host does not grant synthetic symlink creation" /></testcase>'), (1, 1))


if __name__ == "__main__":
    unittest.main()
