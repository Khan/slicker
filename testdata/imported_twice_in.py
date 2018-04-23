from __future__ import absolute_import

import foo.bar
from foo import bar


def f():
    # These are secretly the same!
    foo.bar.some_function()
    bar.some_function()
