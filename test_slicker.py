import ast
import os
import shutil
import tempfile
import unittest

import khodemod

import slicker


class DetermineLocalnamesTest(unittest.TestCase):
    def _assert_localnames(self, actual, expected):
        """Assert imports match the given tuples, but with certain changes."""
        modified_actual = set()
        for imp in actual:
            self.assertIsInstance(imp, slicker.LocalName)
            self.assertIsInstance(imp[2], slicker.Import)
            fullname, localname, (name, alias, start, end, node) = imp
            self.assertIsInstance(node, (ast.Import, ast.ImportFrom))
            modified_actual.add(
                (fullname, localname, (name, alias, start, end)))
        self.assertEqual(modified_actual, expected)

    # TODO(benkraft): Move some of this to a separate ComputeAllImportsTest.
    def test_simple(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, 'import foo\n')),
            {('foo', 'foo', ('foo', 'foo', 0, 10))})

    def test_with_dots(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import foo.bar.baz\n')),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 0, 18))})

    def test_from_import(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo.bar import baz\n')),
            {('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 0, 23))})

    def test_implicit_import(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import foo\n')),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import foo.quux\n')),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.quux', 'foo.quux', 0, 15))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import foo.bar\n')),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.bar', 'foo.bar', 0, 14))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import foo.bar.quux\n')),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.quux', 'foo.bar.quux', 0, 19))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo.bar.baz.quux\n')),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz.quux', 'foo.bar.baz.quux', 0, 23))})

    def test_implicit_from_import(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo.bar import quux\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'from foo import bar\n')),
            {('foo.bar.baz', 'bar.baz', ('foo.bar', 'bar', 0, 19))})

    def test_as_import(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, 'import foo as bar\n')),
            {('foo', 'bar', ('foo', 'bar', 0, 17))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo.bar.baz as quux\n')),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 26))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo.bar import baz as quux\n')),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 31))})

    def test_implicit_as_import(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo as quux\n')),
            {('foo.bar.baz', 'quux.bar.baz', ('foo', 'quux', 0, 18))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo.bar as quux\n')),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 22))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo.bar.quux as bogus\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo import bar as quux\n')),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 27))})
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo.bar import quux as bogus\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import foo.bar.baz.quux as bogus\n')),
            set())

    def test_other_imports(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, 'import bogus\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import bogus.foo.bar.baz\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, 'from bogus import foo\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'from bogus import foo\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from bogus import foo, bar\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'from foo.bogus import bar, baz\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz', slicker.File(None, 'import bar, baz\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(None, 'import bar as foo, baz as quux\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo',
                slicker.File(None, 'import bogus  # (with a comment)\n')),
            set())

    def test_other_junk(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, '# import foo\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo',
                slicker.File(None, '                  # import foo\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo', slicker.File(None, 'def foo(): pass\n')),
            set())
        self._assert_localnames(
            slicker._determine_localnames(
                'foo',
                slicker.File(None,
                             '"""imports are "fun" in a multiline string"""')),
            set())

    def test_with_context(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo',
                slicker.File(
                    None,
                    '# import foo as bar\n'
                    'import os\n'
                    'import sys\n'
                    '\n'
                    'import bogus\n'
                    'import foo\n'
                    '\n'
                    'def foo():\n'
                    '    return 1\n')),
            {('foo', 'foo', ('foo', 'foo', 55, 65))})

    def test_multiple_imports(self):
        self._assert_localnames(
            slicker._determine_localnames(
                'foo.bar.baz',
                slicker.File(
                    None,
                    'import foo\n'
                    'import foo.bar.baz\n'
                    'from foo.bar import baz\n'
                    'import foo.quux\n')),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10)),
             ('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 11, 29)),
             ('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 30, 53)),
             ('foo.bar.baz', 'foo.bar.baz', ('foo.quux', 'foo.quux', 54, 69))})


class DottedPrefixTest(unittest.TestCase):
    def test_dotted_starts_with(self):
        self.assertTrue(slicker._dotted_starts_with('abc', 'abc'))
        self.assertTrue(slicker._dotted_starts_with('abc.de', 'abc'))
        self.assertTrue(slicker._dotted_starts_with('abc.de', 'abc.de'))
        self.assertTrue(slicker._dotted_starts_with('abc.de.fg', 'abc'))
        self.assertTrue(slicker._dotted_starts_with('abc.de.fg', 'abc.de'))
        self.assertTrue(slicker._dotted_starts_with('abc.de.fg', 'abc.de.fg'))
        self.assertFalse(slicker._dotted_starts_with('abc', 'd'))
        self.assertFalse(slicker._dotted_starts_with('abc', 'ab'))
        self.assertFalse(slicker._dotted_starts_with('abc', 'abc.de'))
        self.assertFalse(slicker._dotted_starts_with('abc.de', 'ab'))
        self.assertFalse(slicker._dotted_starts_with('abc.de', 'abc.d'))
        self.assertFalse(slicker._dotted_starts_with('abc.de', 'abc.h'))

    def test_dotted_prefixes(self):
        self.assertItemsEqual(
            slicker._dotted_prefixes('abc'),
            ['abc'])
        self.assertItemsEqual(
            slicker._dotted_prefixes('abc.def'),
            ['abc', 'abc.def'])
        self.assertItemsEqual(
            slicker._dotted_prefixes('abc.def.ghi'),
            ['abc', 'abc.def', 'abc.def.ghi'])


class NamesStartingWithTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            set(slicker._names_starting_with('a', slicker.File(None, 'a\n'))),
            {'a'})
        self.assertEqual(
            set(slicker._names_starting_with(
                'a', slicker.File(None, 'a.b.c\n'))),
            {'a.b.c'})
        self.assertEqual(
            set(slicker._names_starting_with(
                'a', slicker.File(None, 'd.e.f\n'))),
            set())

        self.assertEqual(
            set(slicker._names_starting_with(
                'abc', slicker.File(None, 'abc.de\n'))),
            {'abc.de'})
        self.assertEqual(
            set(slicker._names_starting_with(
                'ab', slicker.File(None, 'abc.de\n'))),
            set())

        self.assertEqual(
            set(slicker._names_starting_with(
                'a', slicker.File(None, '"a.b.c"\n'))),
            set())
        self.assertEqual(
            set(slicker._names_starting_with(
                'a', slicker.File(None, 'import a.b.c\n'))),
            set())
        self.assertEqual(
            set(slicker._names_starting_with(
                'a', slicker.File(None, 'b.c.a.b.c\n'))),
            set())

    def test_in_context(self):
        self.assertEqual(
            set(slicker._names_starting_with('a', slicker.File(
                None,
                'def abc():\n'
                '    if a.b == a.c:\n'
                '        return a.d(a.e + a.f)\n'
                'abc(a.g)\n'))),
            {'a.b', 'a.c', 'a.d', 'a.e', 'a.f', 'a.g'})


class RootTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmpdir = os.path.realpath(
            tempfile.mkdtemp(prefix=(self.__class__.__name__ + '.')))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_root(self):
        shutil.copyfile('testdata/simple_in.py',
                        os.path.join(self.tmpdir, 'in.py'))

        slicker.make_fixes('foo.some_function', 'bar.new_name', 'bar',
                           project_root=self.tmpdir)

        with open('testdata/simple_out.py') as f:
            expected_body = f.read()
        with open(os.path.join(self.tmpdir, 'in.py')) as f:
            actual_body = f.read()
        self.assertMultiLineEqual(expected_body, actual_body)


class FullFileTest(unittest.TestCase):
    maxDiff = None

    def run_test(self, filebase, suggestor,
                 expected_warnings=(), expected_error=None):
        with open('testdata/%s_in.py' % filebase) as f:
            input_text = f.read()
        if expected_error:
            output_text = None
        else:
            with open('testdata/%s_out.py' % filebase) as f:
                output_text = f.read()
        test_frontend = khodemod.TestFrontend(input_text)
        test_frontend.run_suggestor(suggestor)
        test_frontend.run_suggestor(slicker.import_sort_suggestor)
        test_frontend.do_asserts(
            self, output_text, expected_warnings, expected_error)

    def test_simple(self):
        self.run_test(
            'simple',
            slicker.fix_uses_suggestor('foo.some_function',
                                       'bar.new_name', 'bar'))

    def test_whole_file(self):
        self.run_test(
            'whole_file',
            slicker.fix_uses_suggestor('foo', 'bar', 'bar'))

    def test_whole_file_alias(self):
        self.run_test(
            'whole_file_alias',
            slicker.fix_uses_suggestor('foo', 'bar', 'bar', import_alias='baz'))

    def test_same_prefix(self):
        self.run_test(
            'same_prefix',
            slicker.fix_uses_suggestor('foo.bar.some_function',
                                       'foo.baz.some_function', 'foo.baz'))

    def test_implicit(self):
        self.run_test(
            'implicit',
            slicker.fix_uses_suggestor('foo.bar.baz.some_function',
                                       'quux.new_name', 'quux'),
            expected_warnings=[
                khodemod.WarningInfo(
                    filename=khodemod.TestFrontend._FAKE_FILENAME, pos=13,
                    message='This import may be used implicitly.')])

    def test_double_implicit(self):
        self.run_test(
            'double_implicit',
            slicker.fix_uses_suggestor('foo.bar.baz.some_function',
                                       'quux.new_name', 'quux'))

    def test_slicker(self):
        """Test on (a perhaps out of date version of) slicker itself.

        It doesn't do anything super fancy, but it's a decent-sized file at
        least.
        """
        self.run_test(
            'slicker',
            slicker.fix_uses_suggestor('codemod',
                                       'codemod_fork', 'codemod_fork',
                                       import_alias='the_other_codemod'))

    def test_linebreaks(self):
        self.run_test(
            'linebreaks',
            slicker.fix_uses_suggestor('foo.bar.baz.some_function',
                                       'quux.new_name', 'quux'))

    def test_conflict(self):
        self.run_test(
            'conflict',
            slicker.fix_uses_suggestor('foo.bar.interesting_function',
                                       'bar.interesting_function', 'bar',
                                       import_alias='foo'),
            expected_error=khodemod.FatalError(
                khodemod.TestFrontend._FAKE_FILENAME, 0,
                'Your alias will conflict with imports in this file.'))

    def test_conflict_2(self):
        self.run_test(
            'conflict_2',
            slicker.fix_uses_suggestor('bar.interesting_function',
                                       'foo.bar.interesting_function',
                                       'foo.bar'),
            expected_error=khodemod.FatalError(
                khodemod.TestFrontend._FAKE_FILENAME, 0,
                'Your alias will conflict with imports in this file.'))

    def test_unused(self):
        self.run_test(
            'unused',
            slicker.fix_uses_suggestor('foo.bar.some_function',
                                       'quux.some_function', 'quux'),
            expected_warnings=[
                khodemod.WarningInfo(
                    filename=khodemod.TestFrontend._FAKE_FILENAME, pos=49,
                    message='Not removing import with @Nolint.')])

    def test_many_imports(self):
        self.run_test(
            'many_imports',
            slicker.fix_uses_suggestor('foo.quux.replaceme',
                                       'baz.replaced', 'baz'))

    def test_late_import(self):
        self.run_test(
            'late_import',
            slicker.fix_uses_suggestor('foo.bar.some_function',
                                       'quux.some_function', 'quux'))

    def test_mock(self):
        self.run_test(
            'mock',
            slicker.fix_uses_suggestor('foo.bar.some_function',
                                       'quux.some_function', 'quux'))

    def test_comments(self):
        self.run_test(
            'comments',
            slicker.fix_uses_suggestor('foo.bar.some_function',
                                       'quux.mod.some_function', 'quux.mod',
                                       import_alias='al'))

    def test_comments_whole_file(self):
        self.run_test(
            'comments_whole_file',
            slicker.fix_uses_suggestor('foo.bar', 'quux.mod', 'quux.mod',
                                       import_alias='al'))
