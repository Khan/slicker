import logging
import os
import unittest
import shutil
import tempfile

import codemod

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


codemod.Patch.__repr__ = lambda self: 'Patch<%s>' % self.__dict__
codemod.Patch.__eq__ = lambda self, other: self.__dict__ == other.__dict__


class FullFileTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.origdir = os.getcwd()

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)
        os.chdir(self.origdir)

    def run_test(self, filebase, suggestors):
        filename = os.path.join(self.tempdir, '%s_in.py' % filebase)
        shutil.copy("testdata/%s_in.py" % filebase, filename)
        with open('testdata/%s_out.py' % filebase) as f:
            expected_out = f.read()

        os.chdir(self.tempdir)
        path_filter = codemod.path_filter(['py'])
        codemod.base.yes_to_all = True
        for suggestor in suggestors:
            query = codemod.Query(suggestor, path_filter=path_filter,
                                  root_directory=self.tempdir)
            query.run_interactive()

        with open(filename) as f:
            actual_out = f.read()
        self.assertEqual(expected_out, actual_out)

    def test_simple(self):
        self.run_test('simple', [
            slicker.the_suggestor('foo.some_function', 'bar.new_name')])

    def test_implicit(self):
        self.run_test('implicit', [
            slicker.the_suggestor('foo.bar.baz.some_function',
                                  'quux.new_name'),
        ])

    def test_slicker(self):
        """Test on (a perhaps out of date version of) slicker itself.

        It doesn't do anything super fancy, but it's a decent-sized file at
        least.
        """
        self.run_test('slicker', [
            slicker.the_suggestor('codemod.%s' % name,
                                  'codemod_fork.%s' % name,
                                  use_alias='the_other_codemod')
            for name in ['Query', 'Patch', 'path_filter', 'regex_suggestor']])
