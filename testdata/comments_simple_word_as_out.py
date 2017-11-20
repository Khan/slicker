"""File docstring that mentions the util `quux.mod.myfunc()` in util.py.

Some occurrences of 'util' should get renamed but some should not.
It depends if it seems like a utility that is using util as a normal
word or one that is using it as a filename.  If it were email_util
or even util_email it wouldn't be an issue, but just "util" is
pretty confusing.
"""
import quux.mod


_WHITELIST = [
    'quux.mod',
]

def f():
    f = quux.mod.myfunc()
    # We use the util quux.mod.myfunc from util.py.
    self.mock_function('quux.mod.myfunc', lambda: None)
