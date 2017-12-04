from __future__ import absolute_import

# TODO(benkraft): In the case where these two imports are rewritten to be
# identical, maybe we should remove the now-exact duplicate?
import foo.bar
from foo import bar


def f():
    # These are secretly the same!
    foo.bar.some_function()
    bar.some_function()
