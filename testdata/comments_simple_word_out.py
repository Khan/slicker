"""File docstring to exercise `quux.mod.myfunc()` in quux/mod.py.

Some occurrences of 'exercise' should get renamed but some should not.
It depends if it seems like something that exercises "exercise" as a
normal word or one that is using it as a filename.  If it were
content_exercise or exercise_util -- or `quux.mod` -- it wouldn't be
an issue.
"""
import quux.mod


_WHITELIST = [
    'quux.mod',
    'quux.mod.myfunc',
]

def f():
    f = quux.mod.myfunc()
    # We exercise quux.mod.myfunc from quux/mod.py.
    self.mock_function('quux.mod.myfunc', lambda: None)
