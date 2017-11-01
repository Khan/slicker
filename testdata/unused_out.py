from __future__ import absolute_import

import foo.baz  # @UnusedImport
# this is a special import block (and this comment ends up
# in arguably the wrong place!)
import quux


def f():
    quux.some_function()  # needs foo.bar to be imported
