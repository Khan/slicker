from __future__ import absolute_import

# this is a special import block (and this comment ends up
# in arguably the wrong place!)
import foo.bar
import foo.baz  # @UnusedImport


def f():
    foo.bar.some_function()  # needs foo.bar to be imported
