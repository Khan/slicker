from __future__ import absolute_import

import slicker
import test_slicker


class FileMoveSuggestorTest(test_slicker.TestBase):
    def test_move_module_within_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        slicker.make_fixes(['foo'], 'baz',
                           project_root=self.tmpdir)
        self.assertFileIs('baz.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz\n\nbaz.myfunc()\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_move_module_to_a_new_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        slicker.make_fixes(['foo'], 'baz.bang',
                           project_root=self.tmpdir)
        self.assertFileIs('baz/bang.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz.bang\n\nbaz.bang.myfunc()\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_move_module_to_an_existing_directory(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        self.write_file('baz/__init__.py', '')
        slicker.make_fixes(['foo'], 'baz',
                           project_root=self.tmpdir)
        self.assertFileIs('baz/foo.py', 'def myfunc(): return 4\n')
        self.assertFileIs('bar.py', 'import baz.foo\n\nbaz.foo.myfunc()\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_move_module_out_of_a_directory(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('baz.py', 'import foo.bar\n\nfoo.bar.myfunc()\n')
        slicker.make_fixes(['foo.bar'], 'bang',
                           project_root=self.tmpdir)
        self.assertFileIs('bang.py', 'def myfunc(): return 4\n')
        self.assertFileIs('baz.py', 'import bang\n\nbang.myfunc()\n')
        self.assertFileIsNot('foo/bar.py')
        self.assertFalse(self.error_output)
        # TODO(csilvers): assert that the whole dir `foo` has gone away.

    def test_move_module_to_existing_name(self):
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('bar.py', 'import foo\n\nfoo.myfunc()\n')
        with self.assertRaises(ValueError):
            slicker.make_fixes(['foo'], 'bar',
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
        slicker.make_fixes(['foo'], 'newfoo',
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
        self.assertFalse(self.error_output)
        # TODO(csilvers): assert that the whole dir `foo` has gone away.

    def test_move_package_to_existing_name(self):
        self.write_file('foo/__init__.py', '')
        self.write_file('foo/bar.py', 'def myfunc(): return 4\n')
        self.write_file('foo/baz.py', 'def myfunc(): return 5\n')
        self.write_file('qux/__init__.py', '')
        slicker.make_fixes(['foo'], 'qux',
                           project_root=self.tmpdir)
        self.assertFileIs('qux/__init__.py', '')
        self.assertFileIs('qux/foo/__init__.py', '')
        self.assertFileIs('qux/foo/bar.py', 'def myfunc(): return 4\n')
        self.assertFileIs('qux/foo/baz.py', 'def myfunc(): return 5\n')
        self.assertFalse(self.error_output)


class SymbolMoveSuggestorTest(test_slicker.TestBase):
    def test_move_function(self):
        self.write_file('foo.py', 'def myfunc(): return 17\n')
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py', 'def myfunc(): return 17\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_move_class(self):
        self.write_file('foo.py', 'class Classy(object): return 17\n')
        slicker.make_fixes(['foo.Classy'], 'newfoo.Classy',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py', 'class Classy(object): return 17\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_move_constant(self):
        self.write_file('foo.py', 'CACHE = {}\n')
        slicker.make_fixes(['foo.CACHE'], 'newfoo.CACHE',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py', 'CACHE = {}\n')
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_appending_to_existing_file(self):
        # Note since myfunc is at the top of foo.py, and there's only one
        # newline at the bottom of newfoo.py, this tests the case where we add
        # newlines.
        self.write_file('foo.py', 'def myfunc(): return 17\n')
        self.write_file('newfoo.py',
                        ('"""A file with the new version of foo."""\n'
                         'import quux\n\n'
                         'def otherfunc():\n'
                         # Make sure that extra newline won't mess us up:
                         '    return 71\n\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py',
                          ('"""A file with the new version of foo."""\n'
                           'import quux\n\n'
                           'def otherfunc():\n'
                           '    return 71\n\n\n'
                           'def myfunc(): return 17\n'))
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)

    def test_moving_with_context(self):
        self.write_file('foo.py',
                        ('"""A file with the old version of foo."""\n'
                         'import quux\n\n'
                         'def _secretfunc():\n'
                         '    return "secretmonkeys"\n\n\n'
                         '# Does some stuff\n'
                         '# Be careful calling it!\n\n'
                         'def myfunc():\n'
                         '    """Returns a number."""\n'
                         '    return 289\n\n\n'
                         '# Here is another function.\n'
                         'def otherfunc():\n'
                         '    return 1 + 1\n'))
        self.write_file('newfoo.py',
                        ('"""A file with the new version of foo."""\n'
                         'import quux\n\n'
                         'def otherfunc():\n'
                         '    return 71\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py',
                          ('"""A file with the new version of foo."""\n'
                           'import quux\n\n'
                           'def otherfunc():\n'
                           '    return 71\n\n\n'
                           '# Does some stuff\n'
                           '# Be careful calling it!\n\n'
                           'def myfunc():\n'
                           '    """Returns a number."""\n'
                           '    return 289\n'))
        self.assertFileIs('foo.py',
                          ('"""A file with the old version of foo."""\n'
                           'import quux\n\n'
                           'def _secretfunc():\n'
                           '    return "secretmonkeys"\n\n\n'
                           '# Here is another function.\n'
                           'def otherfunc():\n'
                           '    return 1 + 1\n'))
        self.assertFalse(self.error_output)

    def test_renaming_function(self):
        self.write_file('foo.py',
                        ('def myfunc():\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.myfunc'], 'foo.mybetterfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('def mybetterfunc():\n'
                           '    return 17\n'))
        self.assertFalse(self.error_output)

    def test_renaming_decorated_function(self):
        self.write_file('foo.py',
                        ('@decorator\n'
                         'def myfunc():\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.myfunc'], 'foo.mybetterfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('@decorator\n'
                           'def mybetterfunc():\n'
                           '    return 17\n'))
        self.assertFalse(self.error_output)

    def test_renaming_new_style_class(self):
        self.write_file('foo.py',
                        ('class Classy(object):\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.Classy'], 'foo.Classier',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('class Classier(object):\n'
                           '    return 17\n'))
        self.assertFalse(self.error_output)

    def test_renaming_old_style_class(self):
        self.write_file('foo.py',
                        ('class Classy:\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.Classy'], 'foo.Classier',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('class Classier:\n'
                           '    return 17\n'))
        self.assertFalse(self.error_output)

    def test_renaming_decorated_class(self):
        self.write_file('foo.py',
                        ('@decorator\n'
                         'class Classy(object):\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.Classy'], 'foo.Classier',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('@decorator\n'
                           'class Classier(object):\n'
                           '    return 17\n'))
        self.assertFalse(self.error_output)

    def test_renaming_constant(self):
        self.write_file('foo.py', 'CACHE = {}\n')
        slicker.make_fixes(['foo.CACHE'], 'foo._SECRET_CACHE',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py', '_SECRET_CACHE = {}\n')
        self.assertFalse(self.error_output)

    def test_rename_and_move(self):
        self.write_file('foo.py',
                        ('# a class.\n'
                         'class Classy(object):\n'
                         '    return 17\n'))
        slicker.make_fixes(['foo.Classy'], 'newfoo.Classier',
                           project_root=self.tmpdir)
        self.assertFileIs('newfoo.py',
                          ('# a class.\n'
                           'class Classier(object):\n'
                           '    return 17\n'))
        self.assertFileIsNot('foo.py')
        self.assertFalse(self.error_output)
