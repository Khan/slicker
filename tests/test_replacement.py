from __future__ import absolute_import

import os

from slicker import model
from slicker import slicker

import base


class ReplaceInStringTest(base.TestBase):
    def assert_(self, old_module, new_module, old_string, new_string,
                alias=None):
        """Assert that a file that imports old_module rewrites its strings too.

        We create a temp file that imports old_module as alias, and then
        defines a docstring with the contents old_string.  We then rename
        old_module to new_module, and make sure that our temp file not
        only has the import renamed, it has the string renamed as well.
        """
        self.write_file(old_module.replace('.', os.sep) + '.py', '# A file')
        self.write_file('in.py', '"""%s"""\n%s\n\n_ = %s.myfunc()\n'
                        % (old_string,
                           model.Import(
                               old_module, alias or old_module,
                               'absolute', None, None).import_stmt(),
                           alias or old_module))

        slicker.make_fixes([old_module], new_module,
                           project_root=self.tmpdir, automove=False)
        self.assertFalse(self.error_output)

        expected = ('"""%s"""\nimport %s\n\n_ = %s.myfunc()\n'
                    % (new_string, new_module, new_module))
        with open(self.join('in.py')) as f:
            actual = f.read()
        self.assertMultiLineEqual(expected, actual)

    def test_simple(self):
        self.assert_('foo', 'bar.baz', "foo.myfunc", "bar.baz.myfunc")

    def test_word(self):
        self.assert_('exercise', 'foo.bar',
                     ("I will exercise `exercise.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `exercise`."),
                     ("I will exercise `foo.bar.myfunc()` in foo/bar.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `foo.bar`."))

    def test_word_via_as(self):
        self.assert_('qux', 'foo.bar',
                     ("I will exercise `exercise.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `exercise`. And what about "
                      "qux.myfunc()?  Or just 'qux'? `qux`?"),
                     ("I will exercise `foo.bar.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `foo.bar`. And what about "
                      "foo.bar.myfunc()?  Or just 'qux'? `foo.bar`?"),
                     alias='exercise')  # file reads 'import qux as exercise'

    def test_word_via_from(self):
        self.assert_('qux.exercise', 'foo.bar',
                     ("I will exercise `exercise.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `exercise`. And what about "
                      "qux.exercise.myfunc()? Or just 'qux.exercise'? "
                      "`qux.exercise`?"),
                     ("I will exercise `foo.bar.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util but "
                      "does rename `foo.bar`. And what about "
                      "foo.bar.myfunc()? Or just 'foo.bar'? "
                      "`foo.bar`?"),
                     alias='exercise')  # file reads 'from qux import exercise'

    def test_module_and_alias_the_same(self):
        self.assert_('exercise.exercise', 'foo.bar',
                     ("I will exercise `exercise.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util or "
                      "`exercise`. But what about exercise.exercise.myfunc()?"
                      "Or just 'exercise.exercise'? `exercise.exercise`?"),
                     ("I will exercise `exercise.myfunc()` in exercise.py. "
                      "It will not rename 'exercise' and exercises "
                      "not-renaming content_exercise or exercise_util or "
                      "`exercise`. But what about foo.bar.myfunc()?"
                      "Or just 'foo.bar'? `foo.bar`?"),
                     alias='exercise')  # 'from exercise import exercise'

    def test_does_not_rename_files_in_other_dirs(self):
        self.assert_('exercise', 'foo.bar',
                     "otherdir/exercise.py", "otherdir/exercise.py")

    def test_does_not_rename_html_files(self):
        # Regular-english-word case.
        self.assert_('exercise', 'foo.bar',
                     "otherdir/exercise.html", "otherdir/exercise.html")
        # Obviously-a-symbol case.
        self.assert_('exercise_util', 'foo.bar',
                     "dir/exercise_util.html", "dir/exercise_util.html")

    def test_renames_complex_strings_but_not_simple_ones(self):
        self.assert_('exercise', 'foo.bar',
                     "I like 'exercise'", "I like 'exercise'")
        self.assert_('exercise_util', 'foo.bar',
                     "I like 'exercise_util'", "I like 'foo.bar'")

    def test_renames_simple_strings_when_it_is_the_whole_string(self):
        self.assert_('exercise', 'foo.bar',
                     "exercise", "foo.bar")

    def test_word_at_the_end_of_a_sentence(self):
        # Regular-english-word case.
        self.assert_('exercise', 'foo.bar',
                     "I need some exercise.  Yes, exercise.",
                     "I need some exercise.  Yes, exercise.")
        # Obviously-a-symbol case.
        self.assert_('exercise_util', 'foo.bar',
                     "I need to look at exercise_util.  Yes, exercise_util.",
                     "I need to look at foo.bar.  Yes, foo.bar.")
