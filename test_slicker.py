import ast
import os
import shutil
import tempfile
import unittest

import khodemod
import slicker


class TestBase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmpdir = os.path.realpath(
            tempfile.mkdtemp(prefix=(self.__class__.__name__ + '.')))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def join(self, *args):
        return os.path.join(self.tmpdir, *args)

    def copy_file(self, filename):
        """Copy a file from testdata to tmpdir."""
        shutil.copyfile(os.path.join('testdata', filename),
                        os.path.join(self.tmpdir, filename))

    def write_file(self, filename, contents):
        if not os.path.exists(self.join(os.path.dirname(filename))):
            os.makedirs(os.path.dirname(self.join(filename)))
        with open(self.join(filename), 'w') as f:
            f.write(contents)

    def assertFileIs(self, filename, expected):
        with open(self.join(filename)) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def assertFileIsNot(self, filename):
        self.assertFalse(os.path.exists(self.join(filename)))


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


class RootTest(TestBase):
    def test_root(self):
        self.copy_file('simple_in.py')
        with open(self.join('foo.py'), 'w') as f:
            print >>f, "def some_function(): return 4"

        slicker.make_fixes('foo.some_function', 'bar.new_name', 'bar',
                           project_root=self.tmpdir)

        with open(self.join('simple_in.py')) as f:
            actual_body = f.read()
        with open('testdata/simple_out.py') as f:
            expected_body = f.read()
        self.assertMultiLineEqual(expected_body, actual_body)


class MoveSuggestorTest(TestBase):
    def test_move_module_within_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        slicker.make_fixes('foo', 'baz', 'baz',
                           project_root=self.tmpdir)
        self.assertFileIs('baz.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz\n\nbaz.myfunc()\n')
        self.assertFileIsNot('foo.py')

    def test_move_module_to_a_new_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        slicker.make_fixes('foo', 'baz.bang', 'baz.bang',
                           project_root=self.tmpdir)
        self.assertFileIs('baz/bang.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz.bang\n\nbaz.bang.myfunc()\n')
        self.assertFileIsNot('foo.py')

    def test_move_module_to_an_existing_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        self.write_file('baz/__init__.py', '')
        slicker.make_fixes('foo', 'baz', 'baz.foo',
                           project_root=self.tmpdir)
        self.assertFileIs('baz/foo.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz.foo\n\nbaz.foo.myfunc()\n')
        self.assertFileIsNot('foo.py')

    def test_move_module_out_of_a_directory(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('baz.py', 'import foo.bar\n\nfoo.bar.myfunc()\n')
        slicker.make_fixes('foo.bar', 'bang', 'bang',
                           project_root=self.tmpdir)
        self.assertFileIs('bang.py', 'def myfunc(): return 4\n')
        self.assertFileIs('baz.py', 'import bang\n\nbang.myfunc()\n')
        self.assertFileIsNot('foo/bar.py')
        # TODO(csilvers): assert that the whole dir `foo` has gone away.

    def test_move_module_to_existing_name(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        with self.assertRaises(ValueError):
            slicker.make_fixes('foo', 'bar', 'bar',
                               project_root=self.tmpdir)

    def test_move_package(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('foo/baz.py', 'def myfunc(): return 5\n')
        self.write_file('foo/bang/__init__.py', '')
        self.write_file('foo/bang/qux.py', 'qux = True\n')
        self.write_file('toplevel.py',
                        ('import foo.bar\nimport foo.baz\n'
                         'import foo.bang.qux\n\n'
                         'return foo.bar.val + foo.baz.val +'
                         ' foo.bang.qux.qux\n'))
        slicker.make_fixes('foo', 'newfoo', 'newfoo',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo/__init__.py', '')
        self.assertFileIs('newfoo/bar.py', 'def myfunc(): return 4\n')
        self.assertFileIs('newfoo/baz.py', 'def myfunc(): return 5\n')
        self.assertFileIs('newfoo/bang/__init__.py', '')
        self.assertFileIs('newfoo/bang/qux.py', 'qux = True\n')
        self.assertFileIs('toplevel.py',
                          ('import newfoo.bang.qux\nimport newfoo.bar\n'
                           'import newfoo.baz\n\n'
                           'return newfoo.bar.val + newfoo.baz.val +'
                           ' newfoo.bang.qux.qux\n'))
        self.assertFileIsNot('foo/bar.py')
        # TODO(csilvers): assert that the whole dir `foo` has gone away.

    def test_move_package_to_existing_name(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('foo/baz.py', 'def myfunc(): return 5\n')
        self.write_file('qux/__init__.py', '')
        slicker.make_fixes('foo', 'qux', 'qux.foo',
                           project_root=self.tmpdir)
        self.assertFileIs('qux/__init__.py', '')
        self.write_file('qux/foo/__init__.py', '')
        self.write_file('qux/foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('qux/foo/baz.py', 'def myfunc(): return 5\n')


class FixUsesTest(TestBase):
    def run_test(self, filebase, old_fullname, new_fullname,
                 name_to_import, import_alias=None,
                 expected_warnings=(), expected_error=None):
        if expected_error:
            expected = None
        else:
            with open('testdata/%s_out.py' % filebase) as f:
                expected = f.read()

        self.copy_file('%s_in.py' % filebase)

        # Poor-man's mock.
        self.error_output = []
        old_emit = khodemod.emit
        khodemod.emit = lambda txt: self.error_output.append(txt)
        try:
            slicker.make_fixes(old_fullname, new_fullname, name_to_import,
                               import_alias, project_root=self.tmpdir)
        finally:
            khodemod.emit = old_emit

        with open(self.join('%s_in.py' % filebase)) as f:
            actual = f.read()

        if expected:
            self.assertMultiLineEqual(expected, actual)
        else:
            self.assertItemsEqual([expected_error], self.error_output)
        if expected_warnings:
            self.assertItemsEqual(expected_warnings, self.error_output)

    def create_module(self, module_name):
        abspath = self.join(module_name.replace('.', os.sep) + '.py')
        if not os.path.exists(os.path.dirname(abspath)):
            os.makedirs(os.path.dirname(abspath))
        with open(abspath, 'w') as f:
            print >>f, "# A file"

    def test_simple(self):
        self.create_module('foo')
        self.run_test(
            'simple',
            'foo.some_function', 'bar.new_name', 'bar')

    def test_whole_file(self):
        self.create_module('foo')
        self.run_test(
            'whole_file',
            'foo', 'bar', 'bar')

    def test_whole_file_alias(self):
        self.create_module('foo')
        self.run_test(
            'whole_file_alias',
            'foo', 'bar', 'bar', import_alias='baz')

    def test_same_prefix(self):
        self.create_module('foo.bar')
        self.run_test(
            'same_prefix',
            'foo.bar.some_function', 'foo.baz.some_function', 'foo.baz')

    def test_implicit(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'implicit',
            'foo.bar.baz.some_function', 'quux.new_name', 'quux',
            expected_warnings=['WARNING:This import may be used implicitly.\n'
                               '    on implicit_in.py:2 --> '])

    def test_double_implicit(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'double_implicit',
            'foo.bar.baz.some_function', 'quux.new_name', 'quux')

    def test_moving_implicit(self):
        self.create_module('foo.secrets')
        self.run_test(
            'moving_implicit',
            'foo.secrets.lulz', 'quux.new_name', 'quux')

    def test_slicker(self):
        """Test on (a perhaps out of date version of) slicker itself.

        It doesn't do anything super fancy, but it's a decent-sized file at
        least.
        """
        self.create_module('codemod')
        self.run_test(
            'slicker',
            'codemod', 'codemod_fork', 'codemod_fork',
            import_alias='the_other_codemod')

    def test_linebreaks(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'linebreaks',
            'foo.bar.baz.some_function', 'quux.new_name', 'quux')

    def test_conflict(self):
        self.create_module('foo.bar')
        self.run_test(
            'conflict',
            'foo.bar.interesting_function', 'bar.interesting_function', 'bar',
            import_alias='foo',
            expected_error=(
                'ERROR:Your alias will conflict with imports in this file.\n'
                '    on conflict_in.py:1 --> '))

    def test_conflict_2(self):
        self.create_module('bar')
        self.run_test(
            'conflict_2',
            'bar.interesting_function', 'foo.bar.interesting_function',
            'foo.bar',
            expected_error=(
                'ERROR:Your alias will conflict with imports in this file.\n'
                '    on conflict_2_in.py:1 --> import bar'))

    def test_unused(self):
        self.create_module('foo.bar')
        self.run_test(
            'unused',
            'foo.bar.some_function', 'quux.some_function', 'quux',
            expected_warnings=['WARNING:Not removing import with @Nolint.\n'
                               '    on unused_in.py:3 --> '])

    def test_many_imports(self):
        self.create_module('foo.quux')
        self.run_test(
            'many_imports',
            'foo.quux.replaceme', 'baz.replaced', 'baz')

    def test_late_import(self):
        self.create_module('foo.bar')
        self.run_test(
            'late_import',
            'foo.bar.some_function', 'quux.some_function', 'quux')

    def test_mock(self):
        self.create_module('foo.bar')
        self.run_test(
            'mock',
            'foo.bar.some_function', 'quux.some_function', 'quux')

    def test_comments(self):
        self.create_module('foo.bar')
        self.run_test(
            'comments',
            'foo.bar.some_function', 'quux.mod.some_function', 'quux.mod',
            import_alias='al')

    def test_comments_whole_file(self):
        self.create_module('foo.bar')
        self.run_test(
            'comments_whole_file',
            'foo.bar', 'quux.mod', 'quux.mod', import_alias='al')


class ImportSortTest(TestBase):
    def test_third_party_sorting(self):
        self.copy_file('third_party_sorting_in.py')

        os.mkdir(self.join('third_party'))
        for f in ('mycode1.py', 'mycode2.py',
                  'third_party/__init__.py', 'third_party/slicker.py'):
            with open(self.join(f), 'w') as f:
                print >>f, '# A file'

        slicker.make_fixes('third_party_sorting_in', 'out', 'out',
                           project_root=self.tmpdir)

        with open(self.join('out.py')) as f:
            actual = f.read()
        with open('testdata/third_party_sorting_out.py') as f:
            expected = f.read()
        self.assertMultiLineEqual(expected, actual)
