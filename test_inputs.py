from __future__ import absolute_import

import unittest

import inputs
import test_slicker


class InputsTest(test_slicker.TestBase):
    def setUp(self):
        super(InputsTest, self).setUp()
        self.write_file('foo.py', 'def myfunc(): return 4\n')
        self.write_file('dir/__init__.py', '')
        self.write_file('dir/subdir/__init__.py', '')

    def _assert(self, old_fullname, new_fullname, expected):
        actual = list(inputs.expand_and_normalize(self.tmpdir,
                                                  old_fullname, new_fullname))
        self.assertItemsEqual(expected, actual)

    def assert_fails(self, old_fullname, new_fullname, error_text):
        with self.assertRaises(ValueError) as e:
            list(inputs.expand_and_normalize(self.tmpdir,
                                             old_fullname, new_fullname))
        self.assertEqual(error_text, str(e.exception))

    def test_two_modules(self):
        self._assert('foo', 'bar',
                     [('foo', 'bar', False)])

    def test_module_and_file(self):
        self._assert('foo', self.join('bar.py'),
                     [('foo', 'bar', False)])

    def test_module_and_file_in_directory(self):
        self._assert('foo', self.join('bar/baz.py'),
                     [('foo', 'bar.baz', False)])

    def test_two_modules_both_existing(self):
        error = 'Cannot use slicker to merge modules (bar already exists)'
        self.write_file('bar.py', 'def myfunc(): return 4\n')
        self.assert_fails('foo', 'bar', error)

    def test_non_existing_source_module(self):
        error = "Cannot figure out what 'baz' is: module or package not found"
        self.assert_fails('baz', 'bar', error)

    def test_non_existing_source_file(self):
        self.assert_fails(self.join('baz.py'), 'bar',
                          ("Cannot move baz: %s not found"
                           % self.join("baz.py")))
        self.assert_fails(self.join('dir/baz.py'), 'bar',
                          ("Cannot move dir.baz: %s not found"
                           % self.join("dir", "baz.py")))

    def test_module_to_symbol(self):
        self.write_file('baz.py', '')
        error = "Cannot move a module 'foo' to a symbol (baz.newfunc)"
        self.assert_fails('foo', 'baz.newfunc', error)

    def test_module_to_existing_package(self):
        self._assert('foo', 'dir.subdir',
                     [('foo', 'dir.subdir.foo', False)])

    def test_module_to_directory(self):
        self._assert('foo', self.join('dir/subdir'),
                     [('foo', 'dir.subdir.foo', False)])
        self._assert('foo', self.join('dir/subdir/'),
                     [('foo', 'dir.subdir.foo', False)])

    def test_file_to_directory(self):
        self._assert(self.join('foo.py'), self.join('dir/subdir'),
                     [('foo', 'dir.subdir.foo', False)])

    def test_package_to_symbol(self):
        error = "Cannot move a package 'dir' into a symbol (foo.newfunc)"
        self.assert_fails('dir', 'foo.newfunc', error)

    def test_package_to_module(self):
        self.assert_fails('dir', 'foo',
                          "Cannot move a package 'dir' into a module (foo)")

    def test_package_to_new_package(self):
        self._assert('dir', 'newdir',
                     [('dir.__init__', 'newdir.__init__', False),
                      ('dir.subdir.__init__', 'newdir.subdir.__init__', False),
                      ])

    def test_package_to_existing_package(self):
        self.write_file('newdir/__init__.py', '')
        self._assert('dir', 'newdir',
                     [('dir.__init__', 'newdir.dir.__init__', False),
                      ('dir.subdir.__init__', 'newdir.dir.subdir.__init__',
                       False),
                      ])

    def test_symbol_to_new_symbol_in_same_file(self):
        self._assert('foo.myfunc', 'foo.newfunc',
                     [('foo.myfunc', 'foo.newfunc', True)])

    def test_symbol_to_new_symbol_in_new_file(self):
        self._assert('foo.myfunc', 'bar.newfunc',
                     [('foo.myfunc', 'bar.newfunc', True)])

    def test_symbol_to_existing_module(self):
        self.write_file('bar.py', '')
        self._assert('foo.myfunc', 'bar',
                     [('foo.myfunc', 'bar.myfunc', True)])

    def test_symbol_to_new_module(self):
        self._assert('foo.myfunc', 'bar',
                     [('foo.myfunc', 'bar.myfunc', True)])

    def test_symbol_to_new_filename(self):
        self._assert('foo.myfunc', self.join('dir/bar.py'),
                     [('foo.myfunc', 'dir.bar.myfunc', True)])

    def test_symbol_to_new_module_in_subdir(self):
        self._assert('foo.myfunc', 'dir.bar',
                     [('foo.myfunc', 'dir.bar.myfunc', True)])

    def test_symbol_to_new_symbol_in_new_module_in_subdir(self):
        self._assert('foo.myfunc', 'dir.bar.newfunc',
                     [('foo.myfunc', 'dir.bar.newfunc', True)])

    def test_symbol_to_package(self):
        self.assert_fails('foo.myfunc', 'dir',
                          "Cannot move symbol 'foo.myfunc' to a package (dir)")

    @unittest.skip("We don't yet validate this case.")
    def test_symbol_to_existing_symbol(self):
        self.write_file('bar.py', 'def myfunc(): return 4\n')
        error = ("Cannot move symbol 'foo.myfunc' to 'bar': "
                 "'bar' already defines a symbol named 'myfunc'.")
        self.assert_fails('foo.myfunc', 'bar', error)
