from __future__ import absolute_import

import ast
import unittest

from slicker import model
from slicker import util


class ImportProvidesModuleTest(unittest.TestCase):
    def _create_import(self, import_text):
        """Return an Import object for the given text."""
        (imp,) = list(model.compute_all_imports(
            util.File('some_file.py', import_text)))
        return imp

    def test_explicit_imports(self):
        self.assertTrue(model._import_provides_module(
            self._create_import('import foo.bar'), 'foo.bar'))
        self.assertTrue(model._import_provides_module(
            self._create_import('import foo.bar as baz'), 'foo.bar'))
        self.assertTrue(model._import_provides_module(
            self._create_import('from foo import bar'), 'foo.bar'))

    def test_implicit_imports(self):
        self.assertTrue(model._import_provides_module(
            self._create_import('import foo.baz'), 'foo.bar'))

    def test_non_imports(self):
        self.assertFalse(model._import_provides_module(
            self._create_import('import foo.baz as qux'), 'foo.bar'))
        self.assertFalse(model._import_provides_module(
            self._create_import('from foo import baz'), 'foo.bar'))
        self.assertFalse(model._import_provides_module(
            self._create_import('import qux.foo.bar'), 'foo.bar'))


class ComputeAllImportsTest(unittest.TestCase):
    # TODO(benkraft): Move more of the explosion of cases here from
    # LocalNamesFromFullNamesTest and LocalNamesFromLocalNamesTest.
    def _assert_imports(self, actual, expected):
        """Assert the imports match given (name, alias, start, end) tuples."""
        modified_actual = set()
        for imp in actual:
            self.assertIsInstance(imp, model.Import)
            self.assertIsInstance(imp.node, (ast.Import, ast.ImportFrom))
            if imp.relativity == 'absolute':
                modified_actual.add((imp.name, imp.alias, imp.start, imp.end))
            else:
                modified_actual.add((imp.name, imp.alias, imp.start, imp.end,
                                     imp.relativity))

        self.assertEqual(modified_actual, expected)

    def test_simple(self):
        self._assert_imports(
            model.compute_all_imports(
                util.File('some_file.py', 'import foo\n')),
            {('foo', 'foo', 0, 10)})

    def test_relative_import(self):
        self._assert_imports(
            model.compute_all_imports(
                util.File('foo/bar/some_file.py', 'from . import baz\n')),
            {('foo.bar.baz', 'baz', 0, 17, 'explicit')})
        self._assert_imports(
            model.compute_all_imports(
                util.File('foo/some_file.py', 'from .bar import baz\n')),
            {('foo.bar.baz', 'baz', 0, 20, 'explicit')})
        self._assert_imports(
            model.compute_all_imports(
                util.File('foo/bar/junk/some_file.py',
                          'from .. import baz\n')),
            {('foo.bar.baz', 'baz', 0, 18, 'explicit')})
        self._assert_imports(
            model.compute_all_imports(
                util.File('foo/bar/some_file.py', 'from ..bar import baz\n')),
            {('foo.bar.baz', 'baz', 0, 21, 'explicit')})
        self._assert_imports(
            model.compute_all_imports(
                util.File('junk/junk/some_file.py',
                          'from ...foo.bar import baz\n')),
            {('foo.bar.baz', 'baz', 0, 26, 'explicit')})
        self._assert_imports(
            model.compute_all_imports(
                util.File('junk/junk/some_file.py', 'from ... import foo\n')),
            {('foo', 'foo', 0, 19, 'explicit')})

    def test_other_junk(self):
        self.assertFalse(
            model.compute_all_imports(
                util.File('some_file.py', '# import foo\n')))
        self.assertFalse(
            model.compute_all_imports(
                util.File('some_file.py', '                  # import foo\n')))
        self.assertFalse(
            model.compute_all_imports(
                util.File('some_file.py', 'def foo(): pass\n')))
        self.assertFalse(
            model.compute_all_imports(
                util.File('some_file.py',
                          '"""imports are "fun" in a multiline string"""\n')))
        self.assertFalse(
            model.compute_all_imports(
                util.File('some_file.py',
                          'from __future__ import absolute_import\n')))


class LocalNamesFromFullNamesTest(unittest.TestCase):
    def _assert_localnames(self, actual, expected):
        """Assert imports match the given tuples, but with certain changes."""
        modified_actual = set()
        for localname in actual:
            self.assertIsInstance(localname, model.LocalName)
            fullname, ln, imp = localname
            if imp is None:
                modified_actual.add((fullname, ln, None))
            else:
                self.assertIsInstance(imp, model.Import)
                self.assertIsInstance(imp.node, (ast.Import, ast.ImportFrom))
                modified_actual.add(
                    (fullname, ln, (imp.name, imp.alias, imp.start, imp.end)))
        self.assertEqual(modified_actual, expected)

    # TODO(benkraft): Move some of this to a separate ComputeAllImportsTest.
    def test_simple(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo\n'),
                {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 0, 10))})

    def test_with_dots(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar.baz\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 0, 18))})

    def test_from_import(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo.bar import baz\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 0, 23))})

    def test_implicit_import(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.quux', 'foo.quux', 0, 15))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.bar', 'foo.bar', 0, 14))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.quux', 'foo.bar.quux', 0, 19))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar.baz.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz.quux', 'foo.bar.baz.quux', 0, 23))})

    def test_implicit_from_import(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo.bar import quux\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo import bar\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'bar.baz', ('foo.bar', 'bar', 0, 19))})

    def test_as_import(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo as bar\n'),
                {'foo'}),
            {('foo', 'bar', ('foo', 'bar', 0, 17))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar.baz as quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 26))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo.bar import baz as quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 31))})

    def test_implicit_as_import(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo as quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'quux.bar.baz', ('foo', 'quux', 0, 18))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar as quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 22))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import foo.bar.quux as bogus\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo import bar as quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 27))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py',
                          'from foo.bar import quux as bogus\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py',
                          'import foo.bar.baz.quux as bogus\n'),
                {'foo.bar.baz'}),
            set())

    def test_other_imports(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import bogus\n'),
                {'foo'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import bogus.foo.bar.baz\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from bogus import foo\n'),
                {'foo'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from bogus import foo\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from bogus import foo, bar\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'from foo.bogus import bar, baz\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import bar, baz\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py', 'import bar as foo, baz as quux\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File('some_file.py',
                          'import bogus  # (with a comment)\n'),
                {'foo'}),
            set())

    def test_with_context(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File(
                    'some_file.py',
                    ('# import foo as bar\n'
                     'import os\n'
                     'import sys\n'
                     '\n'
                     'import bogus\n'
                     'import foo\n'
                     '\n'
                     'def foo():\n'
                     '    return 1\n')),
                {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 55, 65))})

    def test_multiple_imports(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File(
                    'some_file.py',
                    ('import foo\n'
                     'import foo.bar.baz\n'
                     'from foo.bar import baz\n'
                     # NOTE(benkraft): Since we found a more explicit import,
                     # we don't include this one in the output.
                     'import foo.quux\n')),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10)),
             ('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 11, 29)),
             ('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 30, 53))})

    def test_defined_in_this_file(self):
        self._assert_localnames(
            model.localnames_from_fullnames(
                util.File(
                    'foo/bar.py',
                    'import baz\n'
                    'def f():\n'
                    '    some_function(baz.quux)\n'),
                {'foo.bar.some_function'}),
            {('foo.bar.some_function', 'some_function', None)})

    def test_late_import(self):
        file_info = util.File('some_file.py',
                              ('def f():\n'
                               '    import foo\n'))
        self._assert_localnames(
            model.localnames_from_fullnames(file_info, {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 13, 23))})

        self._assert_localnames(
            model.localnames_from_fullnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info)),
            {('foo', 'foo', ('foo', 'foo', 13, 23))})

        self._assert_localnames(
            model.localnames_from_fullnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info, toplevel_only=True)),
            set())

    def test_within_node(self):
        file_info = util.File(
            'some_file.py',
            ('import foo\n\n\n'
             'def f():\n'
             '    import foo as bar\n'))
        def_node = file_info.tree.body[1]

        self._assert_localnames(
            model.localnames_from_fullnames(file_info, {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 0, 10)),
             ('foo', 'bar', ('foo', 'bar', 26, 43))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info)
            ),
            {('foo', 'foo', ('foo', 'foo', 0, 10)),
             ('foo', 'bar', ('foo', 'bar', 26, 43))})
        self._assert_localnames(
            model.localnames_from_fullnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info, within_node=def_node)),
            {('foo', 'bar', ('foo', 'bar', 26, 43))})


class LocalNamesFromLocalNamesTest(unittest.TestCase):
    def _assert_localnames(self, actual, expected):
        """Assert imports match the given tuples, but with certain changes."""
        modified_actual = set()
        for localname in actual:
            self.assertIsInstance(localname, model.LocalName)
            fullname, ln, imp = localname
            if imp is None:
                modified_actual.add((fullname, ln, None))
            else:
                self.assertIsInstance(imp, model.Import)
                self.assertIsInstance(imp.node, (ast.Import, ast.ImportFrom))
                modified_actual.add(
                    (fullname, ln, (imp.name, imp.alias, imp.start, imp.end)))
        self.assertEqual(modified_actual, expected)

    # TODO(benkraft): Move some of this to a separate ComputeAllImportsTest.
    def test_simple(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo\n'),
                {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 0, 10))})

    def test_with_dots(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.baz\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 0, 18))})

    def test_from_import(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo.bar import baz\n'),
                {'baz'}),
            {('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 0, 23))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo.bar import baz\n'),
                {'foo.bar.baz'}),
            set())

    def test_implicit_import(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.quux', 'foo.quux', 0, 15))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo.bar', 'foo.bar', 0, 14))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.quux', 'foo.bar.quux', 0, 19))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.baz.quux\n'),
                {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz.quux', 'foo.bar.baz.quux', 0, 23))})

    def test_implicit_from_import(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo.bar import quux\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo import bar\n'),
                {'bar.baz'}),
            {('foo.bar.baz', 'bar.baz', ('foo.bar', 'bar', 0, 19))})

    def test_as_import(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo as bar\n'),
                {'bar'}),
            {('foo', 'bar', ('foo', 'bar', 0, 17))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.baz as quux\n'),
                {'quux'}),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 26))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo.bar import baz as quux\n'),
                {'quux'}),
            {('foo.bar.baz', 'quux', ('foo.bar.baz', 'quux', 0, 31))})

        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo as bar\n'),
                {'foo'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.baz as quux\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo.bar import baz as quux\n'),
                {'foo.bar.baz'}),
            set())

    def test_implicit_as_import(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo as quux\n'),
                {'quux.bar.baz'}),
            {('foo.bar.baz', 'quux.bar.baz', ('foo', 'quux', 0, 18))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar as quux\n'),
                {'quux.baz'}),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 22))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.quux as bogus\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'from foo import bar as quux\n'),
                {'quux.baz'}),
            {('foo.bar.baz', 'quux.baz', ('foo.bar', 'quux', 0, 27))})
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py',
                          'from foo.bar import quux as bogus\n'),
                {'foo.bar.baz'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py',
                          'import foo.bar.baz.quux as bogus\n'),
                {'foo.bar.baz'}),
            set())

    def test_other_imports(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import bogus\n'),
                {'foo'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo\n'),
                {'bogus.foo'}),
            set())
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File('some_file.py', 'import foo.bar.baz\n'),
                {'bogus.foo.bar.baz'}),
            set())

    def test_with_context(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File(
                    'some_file.py',
                    ('# import foo as bar\n'
                     'import os\n'
                     'import sys\n'
                     '\n'
                     'import bogus\n'
                     'import foo\n'
                     '\n'
                     'def bogus():\n'
                     '    return 1\n')),
                {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 55, 65))})

    def test_multiple_imports(self):
        file_info = util.File(
            'some_file.py',
            ('import foo\n'
             'import foo.bar.baz\n'
             'from foo.bar import baz\n'
             'import foo.quux\n'))
        self._assert_localnames(
            model.localnames_from_localnames(file_info, {'foo.bar.baz'}),
            {('foo.bar.baz', 'foo.bar.baz', ('foo', 'foo', 0, 10)),
             ('foo.bar.baz', 'foo.bar.baz',
              ('foo.bar.baz', 'foo.bar.baz', 11, 29))})
        self._assert_localnames(
            model.localnames_from_localnames(file_info, {'baz'}),
            {('foo.bar.baz', 'baz', ('foo.bar.baz', 'baz', 30, 53))})

    def test_defined_in_this_file(self):
        self._assert_localnames(
            model.localnames_from_localnames(
                util.File(
                    'foo/bar.py',
                    'import baz\n'
                    'def some_function():\n'
                    '    return 1\n'),
                {'some_function'}),
            {('foo.bar.some_function', 'some_function', None)})

    def test_late_import(self):
        file_info = util.File('some_file.py',
                              ('def f():\n'
                               '    import foo\n'))
        self._assert_localnames(
            model.localnames_from_localnames(file_info, {'foo'}),
            {('foo', 'foo', ('foo', 'foo', 13, 23))})

        self._assert_localnames(
            model.localnames_from_localnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info)),
            {('foo', 'foo', ('foo', 'foo', 13, 23))})

        self._assert_localnames(
            model.localnames_from_localnames(
                file_info, {'foo'}, imports=model.compute_all_imports(
                    file_info, toplevel_only=True)),
            set())

    def test_within_node(self):
        file_info = util.File(
            'some_file.py',
            ('import bar\n\n\n'
             'def f():\n'
             '    import foo as bar\n'))
        def_node = file_info.tree.body[1]

        self._assert_localnames(
            model.localnames_from_localnames(file_info, {'bar'}),
            {('bar', 'bar', ('bar', 'bar', 0, 10)),
             ('foo', 'bar', ('foo', 'bar', 26, 43))})
        self._assert_localnames(
            model.localnames_from_localnames(
                file_info, {'bar'}, imports=model.compute_all_imports(
                    file_info)
            ),
            {('bar', 'bar', ('bar', 'bar', 0, 10)),
             ('foo', 'bar', ('foo', 'bar', 26, 43))})
        self._assert_localnames(
            model.localnames_from_localnames(
                file_info, {'bar'}, imports=model.compute_all_imports(
                    file_info, within_node=def_node)),
            {('foo', 'bar', ('foo', 'bar', 26, 43))})
