"""File docstring that mentions the util `util.myfunc()` in util.py.

Some occurrences of 'util' should get renamed but some should not.
It depends if it seems like a utility that is using util as a normal
word or one that is using it as a filename.  If it were email_util
or even util_email it wouldn't be an issue, but just "util" is
pretty confusing.
"""
import foo.bar as util


_WHITELIST = [
    'util',
]

def f():
    f = util.myfunc()
    # We use the util util.myfunc from util.py.
    self.mock_function('util.myfunc', lambda: None)
