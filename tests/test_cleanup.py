from __future__ import absolute_import

import os

from slicker import slicker

import test_slicker


class RemoveEmptyFilesSuggestorTest(test_slicker.TestBase):
    def test_removes_remaining_whitespace(self):
        self.write_file('foo.py',
                        ('\n\n\n   \n\n  \n'
                         'import bar\n\n\n'
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

    def test_removes_remaining_future_import(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import bar\n\n\n'
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

    def test_warns_remaining_import(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'import asdf  # @UnusedImport\n'
                         'import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import asdf  # @UnusedImport\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertEqual(
            self.error_output,
            [('WARNING:Not removing import with @Nolint.'
              '\n    on foo.py:3 --> import asdf  # @UnusedImport'),
             ('WARNING:This file looks mostly empty; consider removing it.'
              '\n    on foo.py:1 --> from __future__ import absolute_import')])

    def test_warns_remaining_comment(self):
        self.write_file('foo.py',
                        ('# this comment is very important!!!!!111\n'
                         'from __future__ import absolute_import\n\n'
                         'import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('# this comment is very important!!!!!111\n'
                           'from __future__ import absolute_import\n\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertEqual(
            self.error_output,
            ['WARNING:This file looks mostly empty; consider removing it.'
             '\n    on foo.py:1 --> # this comment is very important!!!!!111'])

    def test_warns_remaining_docstring(self):
        self.write_file('foo.py',
                        ('"""This file frobnicates the doodad."""\n'
                         'from __future__ import absolute_import\n\n'
                         'import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('"""This file frobnicates the doodad."""\n'
                           'from __future__ import absolute_import\n\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertEqual(
            self.error_output,
            ['WARNING:This file looks mostly empty; consider removing it.'
             '\n    on foo.py:1 --> """This file frobnicates the doodad."""'])

    def test_warns_remaining_code(self):
        self.write_file('foo.py',
                        ('from __future__ import absolute_import\n\n'
                         'baz = 1\n\n'
                         'import bar\n\n\n'
                         'def myfunc():\n'
                         '    return bar.unrelated_function()\n'))
        slicker.make_fixes(['foo.myfunc'], 'newfoo.myfunc',
                           project_root=self.tmpdir)
        self.assertFileIs('foo.py',
                          ('from __future__ import absolute_import\n\n'
                           'baz = 1\n\n'))
        self.assertFileIs('newfoo.py',
                          ('from __future__ import absolute_import\n\n'
                           'import bar\n\n\n'
                           'def myfunc():\n'
                           '    return bar.unrelated_function()\n'))
        self.assertFalse(self.error_output)


class ImportSortTest(test_slicker.TestBase):
    def test_third_party_sorting(self):
        self.copy_file('third_party_sorting_in.py')

        os.mkdir(self.join('third_party'))
        for f in ('mycode1.py', 'mycode2.py',
                  'third_party/__init__.py', 'third_party/slicker.py'):
            with open(self.join(f), 'w') as f:
                print >>f, '# A file'

        slicker.make_fixes(['third_party_sorting_in'], 'out',
                           project_root=self.tmpdir)

        with open(self.join('out.py')) as f:
            actual = f.read()
        with open('testdata/third_party_sorting_out.py') as f:
            expected = f.read()
        self.assertMultiLineEqual(expected, actual)
        self.assertFalse(self.error_output)
