from __future__ import absolute_import

# TODO(benkraft): In the case where these two imports are rewritten to be
# identical, maybe we should remove the now-exact duplicate?
import quux
import quux


def f():
    # These are secretly the same!
    quux.some_function()
    quux.some_function()
