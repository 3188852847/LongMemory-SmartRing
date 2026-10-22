"""合成报告验证：缺失依赖/失败报告不能通过质量门。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend_quality import ALLOWED_SKIPS, SKIP_REASON_SUBSTRINGS, audit_report


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
            f'<testcase classname="{classname}" name="{name}"><skipped message="{SKIP_REASON_SUBSTRINGS[(classname, name)]}" /></testcase>'
        ), (1, 1))

    def test_missing_console_dependency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未经声明"):
            self.audit('<testcase classname="tests.unit.entrypoints.test_console" name="test_console"><skipped message="aiohttp missing" /></testcase>')

    def test_missing_declared_synthetic_dependencies_cannot_use_old_yaml_exceptions(self):
        for classname, name in (
            ('', 'tests.unit.development.test_sync_role'),
            ('tests.unit.development.test_launcher', 'test_network_sync_preserves_other_configuration_and_backups'),
            ('tests.unit.development.test_local_config_layout', 'test_ui_sync_changes_canonical_then_generation_updates_vendor'),
            ('tests.unit.development.test_hy_voice_budget', 'test_consumption_projection_preserves_canonical_bytes_and_rejects_unknown_target_edits'),
            ('tests.unit.development.test_ad_cosy_continuity', 'test_synthetic_timeline_quantifies_first_answer_duration_and_all_gaps')):
            with self.subTest(classname=classname, name=name), self.assertRaisesRegex(ValueError, '未经声明'):
                self.audit(f'<testcase classname="{classname}" name="{name}"><skipped message="missing dependency" /></testcase>')

    def test_failure_and_collection_error_are_rejected(self):
        for kind in ("failure", "error"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "含失败"):
                self.audit(f'<testcase classname="synthetic" name="failed"><{kind} /></testcase>')

    def test_declared_resource_does_not_allow_new_parameter_or_different_reason(self):
        classname, name = sorted(ALLOWED_SKIPS)[0]
        prefix = '<testcase classname="synthetic" name="passing" />'
        with self.assertRaisesRegex(ValueError, '未经声明'):
            self.audit(prefix + f'<testcase classname="{classname}" name="{name}[unreviewed]"><skipped /></testcase>')
        with self.assertRaisesRegex(ValueError, '原因与声明不符'):
            self.audit(prefix + f'<testcase classname="{classname}" name="{name}"><skipped message="unexpected missing console dependency" /></testcase>')

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

    def test_new_voice_resource_skips_require_reviewed_identity_and_reason(self):
        reviewed = {
            ('tests.unit.development.test_direct_ws_v2',
             'test_actual_first_five_prebuffer_sends_do_not_overwrite'):
                'owner-installed pinned SDK unavailable',
            ('tests.unit.development.test_voice_eos_vad_control',
             'test_native_vad_eos_tail_real_wrappers_and_loopback'):
                'owner-installed websockets runtime unavailable',
        }
        modules = {module for module, _ in reviewed}
        self.assertEqual({key: reason for key, reason in SKIP_REASON_SUBSTRINGS.items()
                          if key[0] in modules}, reviewed)
        passing = '<testcase classname="synthetic" name="passing" />'
        for (module, name), reason in reviewed.items():
            with self.subTest(module=module):
                skip = f'<testcase classname="{module}" name="{name}"><skipped message="{reason}" /></testcase>'
                self.assertEqual(self.audit(passing + skip), (1, 1))
                for wrong_reason in ('', 'missing numpy', 'unexpected SDK failure'):
                    with self.subTest(reason=wrong_reason), self.assertRaisesRegex(ValueError, '原因与声明不符'):
                        self.audit(passing + f'<testcase classname="{module}" name="{name}"><skipped message="{wrong_reason}" /></testcase>')

    def test_new_voice_resource_skips_do_not_allow_other_cases_or_parameters(self):
        passing = '<testcase classname="synthetic" name="passing" />'
        for module, name, reason in (
            ('tests.unit.development.test_direct_ws_v2',
             'test_actual_first_five_prebuffer_sends_do_not_overwrite',
             'owner-installed pinned SDK unavailable'),
            ('tests.unit.development.test_voice_eos_vad_control',
             'test_native_vad_eos_tail_real_wrappers_and_loopback',
             'owner-installed websockets runtime unavailable'),
        ):
            for changed_module, changed_name in (
                (module, name + '[unreviewed]'), (module, name + '_other'),
                (module + '.other', name), (module, 'test_unknown'),
            ):
                with self.subTest(module=changed_module, name=changed_name), self.assertRaisesRegex(ValueError, '未经声明'):
                    self.audit(passing + f'<testcase classname="{changed_module}" name="{changed_name}"><skipped message="{reason}" /></testcase>')


if __name__ == "__main__":
    unittest.main()
