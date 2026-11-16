"""Regression guard for the probe driver's own failure paths.

A missing import or a renamed helper used to surface as a generic
controlled_variant_probe_failed, which looked like a device result. These
tests keep the driver's module surface and its failure categorization honest.
"""
import ast
import builtins
import unittest
from pathlib import Path

import android_ts_node_probe as probe

DRIVER = Path(__file__).parent / 'android_ts_node_probe.py'


class DriverSurfaceTests(unittest.TestCase):
    def test_every_called_helper_is_imported(self):
        """Every module-level name the driver calls must resolve.

        A dropped import (for example the private CA helper) raised a
        NameError inside the run, which the generic handler turned into a
        device-looking failure. This walks the module's own calls.
        """
        tree = ast.parse(DRIVER.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        assigned = {target.id for node in tree.body if isinstance(node, ast.Assign)
                    for target in node.targets if isinstance(target, ast.Name)}
        # Names bound by a nested scope (def, lambda, comprehension) are
        # local to that scope and must not be required at module level.
        nested = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested.add(node.name)
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        nested.add(child.id)
            elif isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp,
                                   ast.DictComp, ast.GeneratorExp)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        nested.add(child.id)
        available = imported | defined | assigned
        missing = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name):
                continue
            name = func.id
            if name in available or name in nested:
                continue
            if name in dir(builtins):
                continue
            missing.add(name)
        self.assertEqual(missing, set(), 'driver calls names that do not exist')
class StageReportingTests(unittest.TestCase):
    def test_stage_reports_class_and_step(self):
        stage = probe.Stage()
        stage.reach('abi-leg')
        report = stage.report(NameError('x'))
        self.assertEqual(report['failureClass'], 'NameError')
        self.assertEqual(report['failureStage'], 'abi-leg')

    def test_stage_defaults_to_variant_start(self):
        self.assertEqual(probe.Stage().name, 'variant-start')

    def test_report_is_bounded(self):
        report = probe.Stage('s').report(ValueError('a' * 4096))
        self.assertLessEqual(len(report['failureClass']), 64)
        self.assertLessEqual(len(report['failureStage']), 64)


if __name__ == '__main__':
    unittest.main()
