import unittest

import slicker


class DetermineImportsTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['import foo\n']),
            {('foo', 'foo', 'foo')})

    def test_with_dots(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar.baz\n']),
            {('foo.bar.baz', 'foo.bar.baz', 'foo.bar.baz')})

    def test_from_import(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo.bar import baz\n']),
            {('foo.bar.baz', 'baz', 'baz')})

    def test_implicit_import(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo\n']),
            {('foo', 'foo', 'foo.bar.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.quux\n']),
            {('foo.quux', 'foo.quux', 'foo.bar.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar\n']),
            {('foo.bar', 'foo.bar', 'foo.bar.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar.quux\n']),
            {('foo.bar.quux', 'foo.bar.quux', 'foo.bar.baz')})

    def test_implicit_from_import(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo.bar import quux\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo import bar\n']),
            {('foo.bar', 'bar', 'bar.baz')})

    def test_as_import(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['import foo as bar\n']),
            {('foo', 'bar', 'bar')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar.baz as quux\n']),
            {('foo.bar.baz', 'quux', 'quux')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo.bar import baz as quux\n']),
            {('foo.bar.baz', 'quux', 'quux')})

    def test_implicit_as_import(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo as quux\n']),
            {('foo', 'quux', 'quux.bar.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar as quux\n']),
            {('foo.bar', 'quux', 'quux.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bar.quux as bogus\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo import bar as quux\n']),
            {('foo.bar', 'quux', 'quux.baz')})
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo.bar import quux as bogus\n']),
            set())

    def test_other_imports(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['import bogus\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import bogus.foo.bar.baz\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['from bogus import foo\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from bogus import foo\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from bogus import foo, bar\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['from foo.bogus import bar, baz\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import bar, baz\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', ['import bar as foo, baz as quux\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['import bogus  # (with a comment)\n']),
            set())

    def test_other_junk(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['# import foo\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['                  # import foo\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['def foo():\n']),
            set())
        self.assertEqual(
            slicker._determine_imports(
                'foo', ['imports are "fun" in a multiline string']),
            set())

    def test_with_context(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo', [
                    '# import foo as bar\n',
                    'import os\n',
                    'import sys\n',
                    '\n',
                    'import bogus\n',
                    'import foo\n',
                    '\n',
                    'def foo():\n',
                    '    return 1\n',
                ]),
            {('foo', 'foo', 'foo')})

    def test_multiple_imports(self):
        self.assertEqual(
            slicker._determine_imports(
                'foo.bar.baz', [
                    'import foo\n',
                    'import foo.bar.baz\n',
                    'from foo.bar import baz\n',
                    'import foo.quux\n',
                ]),
            {('foo', 'foo', 'foo.bar.baz'),
             ('foo.bar.baz', 'foo.bar.baz', 'foo.bar.baz'),
             ('foo.bar.baz', 'baz', 'baz'),
             ('foo.quux', 'foo.quux', 'foo.bar.baz')})

    def test_unhandled_cases(self):
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['import foo, baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['import foo as bar, baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['import foo.bogus, baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['import bar \\', '.baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['from foo import bar, baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['from foo import bogus, baz\n'])
        with self.assertRaises(slicker.UnparsedImportError):
            slicker._determine_imports(
                'foo.bar.baz', ['from foo import (bogus, baz)\n'])
