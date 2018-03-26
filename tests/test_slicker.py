from __future__ import absolute_import

import os
import unittest

import mock
from slicker import model
from slicker import slicker

import base


class RootTest(base.TestBase):
    def test_root(self):
        self.copy_file('simple_in.py')
        with open(self.join('foo.py'), 'w') as f:
            print >>f, "def some_function(): return 4"

        slicker.make_fixes(['foo.some_function'], 'bar.new_name',
                           project_root=self.tmpdir)

        with open(self.join('simple_in.py')) as f:
            actual_body = f.read()
        with open('testdata/simple_out.py') as f:
            expected_body = f.read()
        self.assertMultiLineEqual(expected_body, actual_body)
        self.assertFalse(self.error_output)


class FixUsesTest(base.TestBase):
    def run_test(self, filebase, old_fullname, new_fullname,
                 import_alias=None,
                 expected_warnings=(), expected_error=None):
        if expected_error:
            expected = None
        else:
            with open('testdata/%s_out.py' % filebase) as f:
                expected = f.read()

        self.copy_file('%s_in.py' % filebase)

        slicker.make_fixes([old_fullname], new_fullname,
                           import_alias, project_root=self.tmpdir,
                           # Since we just create placeholder files for the
                           # moved symbol, we won't be able to find it,
                           # which introduces a spurious error.
                           automove=False)

        with open(self.join('%s_in.py' % filebase)) as f:
            actual = f.read()

        # Assert about the errors first, because they may be more informative.
        if expected_warnings:
            self.assertItemsEqual(expected_warnings, self.error_output)
        elif expected:
            self.assertFalse(self.error_output)

        if expected:
            self.assertMultiLineEqual(expected, actual)
        else:
            self.assertItemsEqual([expected_error], self.error_output)

    def create_module(self, module_name):
        self.write_file(module_name.replace('.', os.sep) + '.py', '# A file')

    def test_simple(self):
        self.create_module('foo')
        self.run_test(
            'simple',
            'foo.some_function', 'bar.new_name')

    def test_relative(self):
        self.create_module('somepackage.__init__')
        self.create_module('somepackage.foo')
        self.create_module('foo')  # a red herring
        self.run_test(
            'somepackage/relative',
            'somepackage.foo.some_function', 'bar.new_name')

    @unittest.skip("We don't yet support this, see #16.")
    def test_relative_same_package(self):
        self.create_module('somepackage.__init__')
        self.create_module('somepackage.foo')
        self.create_module('foo')  # a red herring
        self.run_test(
            'somepackage/relative_same_package',
            'somepackage.foo.some_function', 'somepackage.bar.new_name')

    @unittest.skip("We should do a from import, see #22.")
    def test_symbol(self):
        self.create_module('foo')
        self.run_test(
            'symbol',
            'foo.some_function', 'bar.new_name')

    def test_symbol_alias_none(self):
        self.create_module('foo')
        self.run_test(
            'symbol_alias_none',
            'foo.some_function', 'bar.new_name', import_alias='NONE')

    @unittest.skip("We should do a from import, see #22.")
    def test_symbol_import_moving_file(self):
        self.create_module('foo')
        self.run_test(
            'symbol',
            'foo', 'bar')

    @unittest.skip("Known issue, see #20.")
    def test_symbol_import_moving_file_alias_none(self):
        self.create_module('foo')
        self.run_test(
            'symbol_alias_none',
            'foo', 'bar', import_alias='NONE')

    def test_whole_file(self):
        self.create_module('foo')
        self.run_test(
            'whole_file',
            'foo', 'bar')

    def test_whole_file_alias(self):
        self.create_module('foo')
        self.run_test(
            'whole_file_alias',
            'foo', 'bar', import_alias='baz')

    def test_same_prefix(self):
        self.create_module('foo.bar')
        self.run_test(
            'same_prefix',
            'foo.bar.some_function', 'foo.baz.some_function')

    @unittest.skip("TODO(benkraft): We shouldn't consider this a conflict, "
                   "because we'll remove the only conflicting import.")
    def test_same_alias(self):
        self.create_module('foo')
        self.run_test(
            'same_alias',
            'foo.some_function', 'bar.some_function', import_alias='foo')

    @unittest.skip("TODO(benkraft): We shouldn't consider this a conflict, "
                   "because we don't need to touch this file anyway.")
    def test_same_alias_unused(self):
        self.create_module('foo')
        self.run_test(
            'same_alias_unused',
            'foo.some_function', 'bar.some_function', import_alias='foo')

    def test_implicit(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'implicit',
            'foo.bar.baz.some_function', 'quux.new_name',
            expected_warnings=[
                'WARNING:This import may be used implicitly.\n'
                '    on implicit_in.py:6 --> import foo.bar.baz'])

    def test_implicit_and_alias(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'implicit_and_alias',
            'foo.bar.baz.some_function', 'quux.new_name')

    def test_double_implicit(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'double_implicit',
            'foo.bar.baz.some_function', 'quux.new_name')

    def test_moving_implicit(self):
        self.create_module('foo.secrets')
        self.run_test(
            'moving_implicit',
            'foo.secrets.lulz', 'quux.new_name')

    def test_slicker(self):
        """Test on (a perhaps out of date version of) slicker itself.

        It doesn't do anything super fancy, but it's a decent-sized file at
        least.
        """
        self.create_module('codemod')
        self.run_test(
            'slicker',
            'codemod', 'codemod_fork',
            import_alias='the_other_codemod')

    def test_linebreaks(self):
        self.create_module('foo.bar.baz')
        self.run_test(
            'linebreaks',
            'foo.bar.baz.some_function', 'quux.new_name')

    def test_conflict(self):
        self.create_module('foo.bar')
        self.run_test(
            'conflict',
            'foo.bar.interesting_function', 'bar.interesting_function',
            import_alias='foo',
            expected_error=(
                'ERROR:Your alias will conflict with imports in this file.\n'
                '    on conflict_in.py:1 --> import foo.bar'))

    def test_conflict_2(self):
        self.create_module('bar')
        self.run_test(
            'conflict_2',
            'bar.interesting_function', 'foo.bar.interesting_function',
            expected_error=(
                'ERROR:Your alias will conflict with imports in this file.\n'
                '    on conflict_2_in.py:1 --> import quux as foo'))

    def test_unused_conflict(self):
        self.create_module('foo.bar')
        self.run_test(
            'unused_conflict',
            'foo.bar.interesting_function', 'bar.interesting_function',
            import_alias='foo')

    def test_no_conflict_when_moving_to_from(self):
        self.create_module('foo')
        self.run_test(
            'moving_to_from',
            'foo', 'bar.foo',
            import_alias='foo')

    def test_syntax_error(self):
        self.create_module('foo')
        self.run_test(
            'syntax_error',
            'foo.some_function', 'bar.some_function',
            expected_error=(
                "ERROR:Couldn't parse this file: expected an indented block "
                "(<unknown>, line 4)\n"
                "    on syntax_error_in.py:1 --> import foo.some_function"))

    def test_unused(self):
        self.create_module('foo.bar')
        self.run_test(
            'unused',
            'foo.bar.some_function', 'quux.some_function',
            expected_warnings=[
                'WARNING:Not removing import with @Nolint.\n'
                '    on unused_in.py:6 --> import foo.bar  # @UnusedImport'])

    def test_many_imports(self):
        self.create_module('foo.quux')
        self.run_test(
            'many_imports',
            'foo.quux.replaceme', 'baz.replaced')

    def test_late_import(self):
        self.create_module('foo.bar')
        self.run_test(
            'late_import',
            'foo.bar.some_function', 'quux.some_function')

    def test_imported_twice(self):
        self.create_module('foo.bar')
        self.run_test(
            'imported_twice',
            'foo.bar.some_function', 'quux.some_function')

    def test_mock(self):
        self.create_module('foo.bar')
        self.run_test(
            'mock',
            'foo.bar.some_function', 'quux.some_function')

    def test_comments(self):
        self.create_module('foo.bar')
        self.run_test(
            'comments',
            'foo.bar.some_function', 'quux.mod.some_function',
            import_alias='al')

    def test_comments_whole_file(self):
        self.create_module('foo.bar')
        self.run_test(
            'comments_whole_file',
            'foo.bar', 'quux.mod', import_alias='al')

    def test_comments_top_level(self):
        self.create_module('foo')
        self.run_test(
            'comments_top_level',
            'foo', 'quux.mod', import_alias='al')

    def test_source_file(self):
        """Test fixing up uses in the source of the move itself.

        In this case, we need to add an import.
        """
        self.run_test(
            'source_file',
            'source_file_in.myfunc', 'somewhere_else.myfunc')

    def test_source_file_2(self):
        """Test fixing up uses in the source of the move itself.

        In this case, there is an existing import.
        """
        self.run_test(
            'source_file_2',
            'source_file_2_in.myfunc', 'somewhere_else.myfunc')

    def test_destination_file(self):
        """Test fixing up uses in the destination of the move itself.

        In this case, we remove the import, since this is the only reference.
        """
        self.create_module('somewhere_else')
        self.run_test(
            'destination_file',
            'somewhere_else.myfunc', 'destination_file_in.myfunc')

    def test_destination_file_2(self):
        """Test fixing up uses in the destination of the move itself.

        In this case, we don't remove the import; it has other references.
        """
        self.create_module('somewhere_else')
        self.run_test(
            'destination_file_2',
            'somewhere_else.myfunc', 'destination_file_2_in.myfunc')

    def test_unicode(self):
        self.create_module('foo')
        self.run_test(
            'unicode',
            'foo.some_function', 'bar.new_name')

    def test_repeated_name(self):
        self.create_module('foo.foo')
        self.run_test(
            'repeated_name',
            'foo.foo', 'bar.foo.foo')


class AliasTest(base.TestBase):
    def assert_(self, old_module, new_module, alias,
                old_import_line, new_import_line,
                old_extra_text='', new_extra_text='',
                filename='in.py'):
        """Assert that we rewrite imports the way we ought, with aliases."""
        self.write_file(old_module.replace('.', os.sep) + '.py', '# A file')

        # The last word of the import-line is the local-name.
        old_localname = old_import_line.split(' ')[-1]
        new_localname = new_import_line.split(' ')[-1]
        self.write_file(filename,
                        '%s\n\nX = %s.X\n%s\n'
                        % (old_import_line, old_localname, old_extra_text))

        slicker.make_fixes([old_module], new_module, import_alias=alias,
                           project_root=self.tmpdir, automove=False)
        self.assertFalse(self.error_output)

        expected = ('%s\n\nX = %s.X\n%s\n'
                    % (new_import_line, new_localname, new_extra_text))
        with open(self.join(filename)) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def test_auto(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'import foo.bar', 'import baz.bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'from foo import bar', 'from baz import bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'import foo.bar as qux', 'import baz.bang as qux')
        # We treat this as a from-import even though the syntax differs.
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'import foo.bar as bar', 'from baz import bang')

    def test_auto_relative_import(self):
        self.assert_(
            'foo.bar', 'foo.newbar', 'AUTO',
            'from . import bar', 'from . import newbar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'newfoo.bar', 'AUTO',
            'from . import bar', 'from newfoo import bar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'newfoo.newbar', 'AUTO',
            'from . import bar', 'from newfoo import newbar',
            filename='foo/in.py')

    def test_auto_perserves_silly_relative_imports(self):
        self.assert_(
            'foo.bar', 'foo.newbar', 'AUTO',
            'from .foo import bar', 'from .foo import newbar',
            filename='garbage.py')
        self.assert_(
            'foo.bar', 'newfoo.bar', 'AUTO',
            'from .foo import bar', 'from .newfoo import bar',
            filename='garbage.py')

    def test_auto_relative_import_deeper_directory(self):
        # This has to be a separate test from the above, because
        # it has a different directory structure.
        self.assert_(
            'foo.bar.baz', 'foo.bar.newbaz', 'AUTO',
            'from . import baz', 'from . import newbaz',
            filename='foo/bar/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'AUTO',
            'from . import baz', 'from foo.newbar import baz',
            filename='foo/bar/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.bar.newbaz', 'AUTO',
            'from ..bar import baz', 'from ..bar import newbaz',
            filename='foo/char/baz.py')
        self.assert_(
            'foo.bar.baz', 'foo.bar.newbaz', 'AUTO',
            'from ..bar import baz', 'from ..bar import newbaz',
            filename='foo/char/newbaz.py')

    def test_auto_relative_import_sibling_directory(self):
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'AUTO',
            'from ..bar import baz', 'from ..newbar import baz',
            filename='foo/bang/in.py')
        self.assert_(
            'foo.bar.baz', 'newfoo.bar.baz', 'AUTO',
            'from ..bar import baz', 'from newfoo.bar import baz',
            filename='foo/bang/in.py')

    def test_auto_with_symbol_full_import(self):
        self.write_file('foo/bar.py', 'myfunc = lambda: None\n')
        self.write_file('in.py', 'import foo.bar\n\nfoo.bar.myfunc()\n')
        slicker.make_fixes(['foo.bar.myfunc'], self.join('baz/bang.py'),
                           import_alias='AUTO',
                           project_root=self.tmpdir, automove=False)
        self.assertFalse(self.error_output)

        expected = 'import baz.bang\n\nbaz.bang.myfunc()\n'
        with open(self.join('in.py')) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def test_auto_with_symbol_from_import(self):
        self.write_file('foo/bar.py', 'myfunc = lambda: None\n')
        self.write_file('in.py', 'from foo import bar\n\nbar.myfunc()\n')
        slicker.make_fixes(['foo.bar.myfunc'], self.join('baz/bang.py'),
                           import_alias='AUTO',
                           project_root=self.tmpdir, automove=False)
        self.assertFalse(self.error_output)

        expected = 'from baz import bang\n\nbang.myfunc()\n'
        with open(self.join('in.py')) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def test_auto_with_other_imports(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'from foo import bar', 'from baz import bang',
            old_extra_text='import other.ok\n',
            new_extra_text='import other.ok\n')

    def test_auto_with_implicit_imports(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'from foo import bar', 'from baz import bang',
            old_extra_text='import foo.qux\n\nprint foo.qux.CONST\n',
            new_extra_text='import foo.qux\n\nprint foo.qux.CONST\n')

    def test_auto_with_multiple_imports(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'AUTO',
            'from foo import bar', 'from baz import bang',
            old_extra_text='def foo():\n  from foo import bar',
            new_extra_text='def foo():\n  from baz import bang')

    def test_auto_with_conflicting_imports(self):
        # To make the output reproducible, we mock _localnames_from_fullnames
        # to sort its output, so when we choose an arbitrary import to follow,
        # at least we choose a consistent one.
        orig_localnames_from_fullnames = model.localnames_from_fullnames
        with mock.patch('slicker.model.localnames_from_fullnames',
                        lambda *args, **kwargs: list(sorted(
                            orig_localnames_from_fullnames(*args, **kwargs)))):
            self.assert_(
                'foo.bar', 'baz.bang', 'AUTO',
                'from foo import bar', 'from baz import bang',
                old_extra_text='def foo():\n  import foo.bar',
                new_extra_text='def foo():\n  from baz import bang')

    def test_auto_for_toplevel_import(self):
        self.assert_(
            'foo.bar', 'baz', 'AUTO',
            'import foo.bar', 'import baz')
        self.assert_(
            'baz', 'foo.bang', 'AUTO',
            'import baz', 'import foo.bang')

    def test_from(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'FROM',
            'import foo.bar', 'from baz import bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'FROM',
            'from foo import bar', 'from baz import bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'FROM',
            'import foo.bar as qux', 'from baz import bang')

    def test_none(self):
        self.assert_(
            'foo.bar', 'baz.bang', 'NONE',
            'import foo.bar', 'import baz.bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'NONE',
            'from foo import bar', 'import baz.bang')
        self.assert_(
            'foo.bar', 'baz.bang', 'NONE',
            'import foo.bar as qux', 'import baz.bang')
        self.assert_(
            'foo.bar', 'baz.bang', None,
            'import foo.bar', 'import baz.bang')

    def test_makes_relative(self):
        self.assert_(
            'foo.bar', 'foo.newbar', 'RELATIVE',
            'from foo import bar', 'from . import newbar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'foo.newbar', 'RELATIVE',
            'import foo.bar', 'from . import newbar',
            filename='foo/in.py')

    def test_cant_make_relative(self):
        self.assert_(
            'foo.bar', 'newfoo.bar', 'RELATIVE',
            'from foo import bar', 'from newfoo import bar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'newfoo.bar', 'RELATIVE',
            'import foo.bar', 'from newfoo import bar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'newfoo.newbar', 'RELATIVE',
            'from foo import bar', 'from newfoo import newbar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'newfoo.newbar', 'RELATIVE',
            'import foo.bar', 'from newfoo import newbar',
            filename='foo/in.py')
        self.assert_(
            'foo.bar', 'foo.newbar', 'RELATIVE',
            'from foo import bar', 'from foo import newbar',
            filename='garbage.py')
        self.assert_(
            'foo.bar', 'foo.newbar', 'RELATIVE',
            'import foo.bar', 'from foo import newbar',
            filename='garbage.py')
        self.assert_(
            'foo.bar', 'newfoo.bar', 'RELATIVE',
            'from foo import bar', 'from newfoo import bar',
            filename='garbage.py')
        self.assert_(
            'foo.bar', 'newfoo.bar', 'RELATIVE',
            'import foo.bar', 'from newfoo import bar',
            filename='garbage.py')

    def test_relative_deeper_directory(self):
        self.assert_(
            'foo.bar.baz', 'foo.bar.newbaz', 'RELATIVE',
            'from foo.bar import baz', 'from . import newbaz',
            filename='foo/bar/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.bar.newbaz', 'RELATIVE',
            'import foo.bar.baz', 'from . import newbaz',
            filename='foo/bar/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'RELATIVE',
            'from foo.bar import baz', 'from foo.newbar import baz',
            filename='foo/bar/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'RELATIVE',
            'import foo.bar.baz', 'from foo.newbar import baz',
            filename='foo/bar/in.py')

    def test_relative_sibling_directories(self):
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'RELATIVE',
            'from foo.bar import baz', 'from foo.newbar import baz',
            filename='foo/bang/in.py')
        self.assert_(
            'foo.bar.baz', 'foo.newbar.baz', 'RELATIVE',
            'import foo.bar.baz', 'from foo.newbar import baz',
            filename='foo/bang/in.py')
        self.assert_(
            'foo.bar.baz', 'newfoo.bar.baz', 'RELATIVE',
            'from foo.bar import baz', 'from newfoo.bar import baz',
            filename='foo/bang/in.py')
        self.assert_(
            'foo.bar.baz', 'newfoo.bar.baz', 'RELATIVE',
            'import foo.bar.baz', 'from newfoo.bar import baz',
            filename='foo/bang/in.py')


class FixMovedRegionSuggestorTest(base.TestBase):
    def test_rename_references_self(self):
        self.write_file('foo.py',
                        ('something = 1\n'
                         'def fib(n):\n'
                         '    return fib(n - 1) + fib(n - 2)\n'))
        slicker.make_fixes(['foo.fib'], 'foo.slow_fib',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('something = 1\n'
                           'def slow_fib(n):\n'
                           '    return slow_fib(n - 1) + slow_fib(n - 2)\n'))
        self.assertFalse(self.error_output)

    def test_move_references_self(self):
        self.write_file('foo.py',
                        ('something = 1\n'
                         'def fib(n):\n'
                         '    return fib(n - 1) + fib(n - 2)\n'))
        slicker.make_fixes(['foo.fib'], 'newfoo.fib',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          'something = 1\n')
        self.assertFileIs('newfoo.py',
                          ('def fib(n):\n'
                           '    return fib(n - 1) + fib(n - 2)\n'))
        self.assertFalse(self.error_output)

    def test_rename_and_move_references_self(self):
        self.write_file('foo.py',
                        ('something = 1\n'
                         'def fib(n):\n'
                         '    return fib(n - 1) + fib(n - 2)\n'))
        slicker.make_fixes(['foo.fib'], 'newfoo.slow_fib',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          'something = 1\n')
        self.assertFileIs('newfoo.py',
                          ('def slow_fib(n):\n'
                           '    return slow_fib(n - 1) + slow_fib(n - 2)\n'))
        self.assertFalse(self.error_output)

    def test_rename_and_move_references_self_via_self_import(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import foo\n\n\n'
                         'something = 1\n'
                         'def fib(n):\n'
                         '    return foo.fib(n - 1) + foo.fib(n - 2)\n'))
        slicker.make_fixes(['foo.fib'], 'newfoo.slow_fib',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           '\n\n'  # TODO(benkraft): remove extra newlines
                           'something = 1\n'))
        self.assertFileIs('newfoo.py',
                          ('def slow_fib(n):\n'
                           '    return slow_fib(n - 1) + slow_fib(n - 2)\n'))
        self.assertFalse(self.error_output)

    def test_rename_and_move_references_self_via_late_self_import(self):
        self.write_file('foo.py',
                        ('something = 1\n'
                         'def fib(n):\n'
                         '    import foo\n'
                         '    return foo.fib(n - 1) + foo.fib(n - 2)\n'))
        slicker.make_fixes(['foo.fib'], 'newfoo.slow_fib',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          'something = 1\n')
        self.assertFileIs('newfoo.py',
                          ('def slow_fib(n):\n'
                           '    return slow_fib(n - 1) + slow_fib(n - 2)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module(self):
        self.write_file('foo.py',
                        ('const = 1\n\n\n'
                         'def f():\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return f(const)\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('const = 1\n\n\n'
                           'def f():\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'def myfunc():\n'
                           '    return foo.f(foo.const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_for_class_vars(self):
        self.write_file('foo.py',
                        ('const = 1\n\n\n'
                         'class C(object):\n'
                         '    VAR = 1\n\n\n'
                         'def myfunc():\n'
                         '    return C.VAR + 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('const = 1\n\n\n'
                           'class C(object):\n'
                           '    VAR = 1\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'def myfunc():\n'
                           '    return foo.C.VAR + 1\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_already_imported(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'const = 1\n\n\n'
                         'def f():\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return f(const)\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import foo\n\n\n'
                         'def f():\n'
                         '    return foo.f()\n'))

        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           'const = 1\n\n\n'
                           'def f():\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'def f():\n'
                           '    return foo.f()\n\n\n'
                           'def myfunc():\n'
                           '    return foo.f(foo.const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_already_imported_via_relative_import(self):
        self.write_file('somepackage/foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'const = 1\n\n\n'
                         'def f():\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return f(const)\n'))
        self.write_file('somepackage/newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'from . import foo\n\n\n'
                         'def f():\n'
                         '    return foo.f()\n'))

        slicker.make_fixes(['somepackage.foo.myfunc'],
                           'somepackage.newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('somepackage/foo.py',
                          ('from __future__ import absolute_import\n\n'
                           'const = 1\n\n\n'
                           'def f():\n'
                           '    pass\n'))
        self.assertFileIs('somepackage/newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import foo\n\n\n'
                           'def f():\n'
                           '    return foo.f()\n\n\n'
                           'def myfunc():\n'
                           '    return foo.f(foo.const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_imports_self(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import foo\n\n\n'
                         'const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return foo.f(foo.const)\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           '\n\n'  # TODO(benkraft): remove extra newlines
                           'const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'def myfunc():\n'
                           '    return foo.f(foo.const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_imports_self_via_relative_import(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'from . import foo\n\n\n'
                         'const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return foo.f(foo.const)\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           '\n\n'  # TODO(benkraft): remove extra newlines
                           'const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import foo\n\n\n'
                           'def myfunc():\n'
                           '    return foo.f(foo.const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_new_module(self):
        self.write_file('foo.py',
                        ('import newfoo\n\n\n'
                         'def myfunc():\n'
                         '    return newfoo.f(newfoo.const)\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_new_module_via_alias(self):
        self.write_file('foo.py',
                        ('import newfoo as bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.f(bar.const)\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_new_module_via_symbol_import(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'from newfoo import const\n'
                         'from newfoo import f\n\n\n'
                         'def myfunc():\n'
                         '    return f(const)\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'const = 1\n\n\n'
                         'def f():\n'
                         '    pass\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'const = 1\n\n\n'
                           'def f():\n'
                           '    pass\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_new_module_via_relative_import(self):
        self.write_file('package/foo.py',
                        ('from . import newfoo\n\n\n'
                         'def myfunc():\n'
                         '    return newfoo.f(newfoo.const)\n'))
        self.write_file('package/newfoo.py',
                        ('const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n'))
        slicker.make_fixes(['package.foo.myfunc'], 'package.newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('package/foo.py')
        self.assertFileIs('package/newfoo.py',
                          ('const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_old_module_via_implicit_self_import(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py',
                        ('import foo.baz\n\n\n'
                         'def f():\n'
                         '    pass\n\n\n'
                         'def myfunc():\n'
                         '    return foo.bar.f()\n'))
        slicker.make_fixes(['foo.bar.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo/bar.py',
                          ('def f():\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           # TODO(benkraft): Should we fix this up to foo.bar?
                           'import foo.baz\n\n\n'
                           'def myfunc():\n'
                           '    return foo.bar.f()\n'))
        self.assertEqual(self.error_output,
                         ['WARNING:This import may be used implicitly.'
                          '\n    on newfoo.py:3 --> import foo.baz'])

    def test_uses_new_module_via_implicit_import(self):
        self.write_file('foo.py',
                        ('import newfoo.baz\n\n\n'
                         'def myfunc():\n'
                         '    return newfoo.bar.f(newfoo.bar.const)\n'))
        self.write_file('newfoo/__init__.py', '')
        self.write_file('newfoo/bar.py',
                        ('const = 1\n\n\n'
                         'def f(x):\n'
                         '    pass\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.bar.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo/bar.py',
                          ('const = 1\n\n\n'
                           'def f(x):\n'
                           '    pass\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_uses_new_module_imports_self(self):
        self.write_file('foo.py',
                        ('import newfoo\n\n\n'
                         'def myfunc():\n'
                         '    return newfoo.f(newfoo.const)\n'))
        self.write_file('newfoo.py',
                        ('import newfoo\n\n\n'
                         'const = 1\n\n\n'
                         'def f(x):\n'
                         '    return newfoo.const\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('import newfoo\n\n\n'
                           'const = 1\n\n\n'
                           'def f(x):\n'
                           '    return newfoo.const\n\n\n'
                           'def myfunc():\n'
                           '    return f(const)\n'))
        self.assertFalse(self.error_output)

    def test_move_a_name_and_its_prefix(self):
        self.write_file('foo.py', 'class Foo(object): var = 1\n')
        self.write_file('bar.py',
                        'import foo\n\nc = MyClass(foo.Foo, foo.Foo.myvar)')
        slicker.make_fixes(['bar.c'], 'bazbaz',
                           project_root=self.tmpdir)
        self.assertFalse(self.error_output)

    def test_combine_two_files(self):
        self.write_file('foo.py', 'class Foo(object): var = 1\n')
        self.write_file('bar.py',
                        'import foo\n\nc = MyClass(foo.Foo, foo.Foo.myvar)')
        slicker.make_fixes(['foo.Foo', 'bar.c'], 'bazbaz',
                           project_root=self.tmpdir)
        self.assertFalse(self.error_output)

    def test_move_references_everything_in_sight(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import newfoo\n\n\n'
                         'def f(x):\n'
                         '    pass\n\n\n'
                         'def myfunc(n):\n'
                         '    return myfunc(n-1) + f(newfoo.const)\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           '\n\n'  # TODO(benkraft): remove extra newlines
                           'def f(x):\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'const = 1\n\n\n'
                           'def myfunc(n):\n'
                           '    return myfunc(n-1) + foo.f(const)\n'))
        self.assertFalse(self.error_output)

    def test_rename_and_move_references_everything_in_sight(self):
        self.write_file('foo.py',
                        ('import newfoo\n\n\n'
                         'def f(x):\n'
                         '    pass\n\n\n'
                         'def myfunc(n):\n'
                         '    return myfunc(n-1) + f(newfoo.const)\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.mynewerfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('def f(x):\n'
                           '    pass\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'const = 1\n\n\n'
                           'def mynewerfunc(n):\n'
                           '    return mynewerfunc(n-1) + foo.f(const)\n'))
        self.assertFalse(self.error_output)

    def test_move_references_same_name_in_both(self):
        self.write_file('foo.py',
                        ('import newfoo\n\n\n'
                         'def f(g):\n'
                         '    return g(1)\n\n\n'
                         'def myfunc(n):\n'
                         '    return f(newfoo.f)\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n\n\n'
                         'def f(x):\n'
                         '    return x\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('def f(g):\n'
                           '    return g(1)\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import foo\n\n\n'
                           'const = 1\n\n\n'
                           'def f(x):\n'
                           '    return x\n\n\n'
                           'def myfunc(n):\n'
                           '    return foo.f(f)\n'))
        self.assertFalse(self.error_output)

    def test_late_import_in_moved_region(self):
        self.write_file('foo.py',
                        ('def myfunc():\n'
                         '    import newfoo\n'
                         '    return newfoo.const\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('const = 1\n\n\n'
                           'def myfunc():\n'
                           '    return const\n'))
        self.assertFalse(self.error_output)

    def test_late_import_elsewhere(self):
        self.write_file('foo.py',
                        ('def f():\n'
                         '    import newfoo\n'
                         '    return newfoo.const\n\n\n'
                         'def myfunc():\n'
                         '    import newfoo\n'
                         '    return newfoo.const\n'))
        self.write_file('newfoo.py',
                        ('const = 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('def f():\n'
                           '    import newfoo\n'
                           '    return newfoo.const\n'))
        self.assertFileIs('newfoo.py',
                          ('const = 1\n\n\n'
                           'def myfunc():\n'
                           '    return const\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import(self):
        self.write_file('foo.py',
                        ('import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_relative_import_same_package(self):
        self.write_file('foo/this.py',
                        ('from . import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'foo.that.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('foo/that.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_relative_import_moved_to_new_package(self):
        self.write_file('foo/this.py',
                        ('from . import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'newfoo.this.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('newfoo/this.py',
                          ('from __future__ import absolute_import\n\n'
                           'from foo import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_aliased_import(self):
        self.write_file('foo.py',
                        ('import baz as bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import baz as bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_symbol_import(self):
        self.write_file('foo.py',
                        ('from bar import unrelated_function\n\n\n'
                         'def myfunc():\n'
                         '    return unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'from bar import unrelated_function\n\n\n'
                           'def myfunc():\n'
                           '    return unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_implicit_import(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'def myfunc():\n'
                         '    return bar.qux.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           # TODO(benkraft): Should we fix this up to bar.qux?
                           'import bar.baz\n\n\n'
                           'def myfunc():\n'
                           '    return bar.qux.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_import(self):
        self.write_file('foo.py',
                        ('import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_relative_import(self):
        self.write_file('foo/this.py',
                        ('from . import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('foo/that.py',
                        ('from __future__ import absolute_import\n\n'
                         'from . import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'foo.that.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('foo/that.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_relative_import_old_import_absolute(self):
        self.write_file('foo/this.py',
                        ('from foo import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('foo/that.py',
                        ('from __future__ import absolute_import\n\n'
                         'from . import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'foo.that.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('foo/that.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_relative_import_new_import_absolute(self):
        self.write_file('foo/this.py',
                        ('from . import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('foo/that.py',
                        ('from __future__ import absolute_import\n\n'
                         'from foo import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'foo.that.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('foo/that.py',
                          ('from __future__ import absolute_import\n\n'
                           'from foo import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_relative_import_old_package(self):
        self.write_file('foo/this.py',
                        ('from . import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('newfoo/this.py',
                        ('from __future__ import absolute_import\n\n'
                         'from foo import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'newfoo.this.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('newfoo/this.py',
                          ('from __future__ import absolute_import\n\n'
                           'from foo import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_relative_import_new_package(self):
        self.write_file('foo/this.py',
                        ('from newfoo import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('newfoo/this.py',
                        ('from __future__ import absolute_import\n\n'
                         'from . import bar\n\n\n'
                         'const = bar.thingy\n'))
        slicker.make_fixes(['foo.this.myfunc'], 'newfoo.this.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo/this.py')
        self.assertFileIs('newfoo/this.py',
                          ('from __future__ import absolute_import\n\n'
                           'from . import bar\n\n\n'
                           'const = bar.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import_with_mismatched_name(self):
        self.write_file('foo.py',
                        ('import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar as baz\n\n\n'
                         'const = baz.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar as baz\n\n\n'
                           'const = baz.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return baz.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_symbol_import(self):
        self.write_file('foo.py',
                        ('from bar import unrelated_function\n\n\n'
                         'def myfunc():\n'
                         '    return unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'from bar import unrelated_function\n\n\n'
                         'const = unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'from bar import unrelated_function\n\n\n'
                           'const = unrelated_function()\n\n\n'
                           'def myfunc():\n'
                           '    return unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_symbol_import_mismatch(self):
        self.write_file('foo.py',
                        ('import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'from bar import unrelated_function\n\n\n'
                         'const = unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n'
                           'from bar import unrelated_function\n\n\n'
                           'const = unrelated_function()\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import_with_similar_existing_import(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'def myfunc():\n'
                         '    return bar.baz.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar.qux\n\n\n'
                         'const = bar.qux.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar.baz\n'
                           'import bar.qux\n\n\n'
                           'const = bar.qux.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.baz.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_implicit_import(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'def myfunc():\n'
                         '    return bar.qux.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar.baz\n\n\n'
                         'const = bar.qux.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           # TODO(benkraft): Should we fix this up to bar.qux?
                           'import bar.baz\n\n\n'
                           'const = bar.qux.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.qux.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_existing_implicit_import_used_explicitly(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'def myfunc():\n'
                         '    return bar.qux.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar.baz\n\n\n'
                         'const = bar.baz.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           # TODO(benkraft): Should we fix this up to bar.qux?
                           'import bar.baz\n\n\n'
                           'const = bar.baz.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.qux.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_implicit_import_with_existing_explicit_import(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'def myfunc():\n'
                         '    return bar.qux.unrelated_function()\n'))
        self.write_file('newfoo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar.qux\n\n\n'
                         'const = bar.qux.thingy\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           # TODO(benkraft): We shouldn't add this.
                           'import bar.baz\n'
                           'import bar.qux\n\n\n'
                           'const = bar.qux.thingy\n\n\n'
                           'def myfunc():\n'
                           '    return bar.qux.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    @unittest.skip("""Ideally, we wouldn't remove this.""")
    def test_doesnt_touch_unrelated_import_in_old(self):
        self.write_file('foo.py',
                        ('import unrelated\n\n\n'
                         'def myfunc():\n'
                         '    return 1\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('import unrelated\n'))
        self.assertFileIs('newfoo.py',
                          ('def myfunc():\n'
                           '    return 1\n'))
        self.assertFalse(self.error_output)

    def test_doesnt_touch_unrelated_import_in_new(self):
        self.write_file('foo.py',
                        ('def myfunc():\n'
                         '    return 1\n'))
        self.write_file('newfoo.py',
                        ('import unrelated\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIsNot('foo.py')
        self.assertFileIs('newfoo.py',
                          ('import unrelated\n\n\n'
                           'def myfunc():\n'
                           '    return 1\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import_used_elsewhere(self):
        self.write_file('foo.py',
                        ('import bar\n\n\n'
                         'const = bar.something\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('import bar\n\n\n'
                           'const = bar.something\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import_related_import_used_elsewhere(self):
        self.write_file('foo.py',
                        ('import bar.baz\n'
                         'import bar.qux\n\n\n'
                         'const = bar.baz.something\n\n\n'
                         'def myfunc():\n'
                         '    return bar.qux.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('import bar.baz\n\n\n'
                           'const = bar.baz.something\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar.qux\n\n\n'
                           'def myfunc():\n'
                           '    return bar.qux.unrelated_function()\n'))
        self.assertFalse(self.error_output)

    def test_uses_other_import_used_implicitly_elsewhere(self):
        self.write_file('foo.py',
                        ('import bar.baz\n\n\n'
                         'const = bar.qux.something\n\n\n'
                         'def myfunc():\n'
                         '    return bar.baz.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('import bar.baz\n\n\n'
                           'const = bar.qux.something\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar.baz\n\n\n'
                           'def myfunc():\n'
                           '    return bar.baz.unrelated_function()\n'))
        self.assertEqual(self.error_output,
                         ['WARNING:This import may be used implicitly.'
                          '\n    on foo.py:1 --> import bar.baz'])
