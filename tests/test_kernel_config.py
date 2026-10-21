import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/rpd-backlight-m10'
spec = importlib.util.spec_from_file_location('kernel_config', PORT / 'check-kernel-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class KernelConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = self.root / 'expected.config'
        self.actual = self.root / 'actual.config'
        self.original = (PORT / 'kernel.config').read_text()
        self.expected.write_text(self.original)
        self.actual.write_text(self.original)
        (self.root / 'scripts').mkdir()
        for name in ['Makefile.btf', 'Kbuild.include']:
            shutil.copyfile(ROOT / 'tests/data' / ('m10-' + name),
                            self.root / 'scripts' / name)

    def test_pahole_132_retains_actual_kernel_btf_flags(self):
        self.actual.write_text(self.original.replace('CONFIG_PAHOLE_VERSION=131',
                                                    'CONFIG_PAHOLE_VERSION=132'))
        config.check(self.expected, self.actual, self.root)

    def test_older_tool_with_different_encoding_flags_is_rejected(self):
        self.actual.write_text(self.original.replace('CONFIG_PAHOLE_VERSION=131',
                                                    'CONFIG_PAHOLE_VERSION=130'))
        with self.assertRaisesRegex(ValueError, 'BTF flags'):
            config.check(self.expected, self.actual, self.root)

    def test_new_kernel_feature_threshold_is_not_silently_ignored(self):
        p = self.root / 'scripts/Makefile.btf'
        p.write_text(p.read_text().replace('export PAHOLE_FLAGS :=',
            'pahole-flags-$(call test-ge, $(pahole-ver), 132) += --new-feature\n'
            'export PAHOLE_FLAGS :='))
        self.actual.write_text(self.original.replace('CONFIG_PAHOLE_VERSION=131',
                                                    'CONFIG_PAHOLE_VERSION=132'))
        with self.assertRaisesRegex(ValueError, 'BTF flags'):
            config.check(self.expected, self.actual, self.root)

    def test_module_btf_resolver_flags_are_also_checked(self):
        p = self.root / 'scripts/Makefile.btf'
        p.write_text(p.read_text().replace('export RESOLVE_BTFIDS_FLAGS :=',
            'ifneq ($(KBUILD_EXTMOD),)\n'
            'resolve-btfids-flags-$(call test-ge, $(pahole-ver), 132) += --new-module-feature\n'
            'endif\nexport RESOLVE_BTFIDS_FLAGS :='))
        self.actual.write_text(self.original.replace('CONFIG_PAHOLE_VERSION=131',
                                                    'CONFIG_PAHOLE_VERSION=132'))
        with self.assertRaisesRegex(ValueError, 'BTF flags'):
            config.check(self.expected, self.actual, self.root)

    def test_real_kernel_configuration_changes_are_rejected(self):
        for setting in ['CONFIG_DEBUG_INFO_BTF', 'CONFIG_DEBUG_INFO_BTF_MODULES',
                        'CONFIG_PAHOLE_HAS_BTF_TAG', 'CONFIG_PAHOLE_HAS_LANG_EXCLUDE',
                        'CONFIG_ARM64']:
            with self.subTest(setting=setting):
                self.assertIn(setting + '=y', self.original)
                self.actual.write_text(self.original.replace(setting + '=y',
                                                            '# ' + setting + ' is not set'))
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    config.check(self.expected, self.actual, self.root)

    def test_module_abi_and_compiler_changes_are_rejected(self):
        for old, new in [('# CONFIG_MODVERSIONS is not set', 'CONFIG_MODVERSIONS=y'),
                         ('CONFIG_CLANG_VERSION=230103', 'CONFIG_CLANG_VERSION=230104')]:
            with self.subTest(setting=old):
                self.assertIn(old, self.original)
                self.actual.write_text(self.original.replace(old, new))
                with self.assertRaisesRegex(ValueError, 'configuration changed'):
                    config.check(self.expected, self.actual, self.root)

    def test_missing_or_invalid_tool_metadata_is_rejected(self):
        for replacement in ['', 'CONFIG_PAHOLE_VERSION=invalid']:
            with self.subTest(replacement=replacement):
                self.actual.write_text(self.original.replace('CONFIG_PAHOLE_VERSION=131', replacement))
                with self.assertRaisesRegex(ValueError, 'one numeric'):
                    config.check(self.expected, self.actual, self.root)

    def test_native_link_capability_exception_remains_supported(self):
        self.expected.write_text(self.original.replace('CONFIG_CC_CAN_LINK=y\n', ''))
        self.actual.write_text(self.expected.read_text() + 'CONFIG_CC_CAN_LINK=y\n')
        config.check(self.expected, self.actual, self.root)
