from __future__ import absolute_import

# this is a special import block (and this comment ends up
# in arguably the wrong place!)
# TODO(benkraft): In the case where these two imports are rewritten to be
# identical, maybe we should remove the now-exact duplicate?
import foo.other
from foo.bar import baz


def f():
    """Calls some stuff in foo, mwahaha!"""
    baz.some_function()
    foo.bar.baz.some_function()
