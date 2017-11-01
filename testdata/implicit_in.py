from __future__ import absolute_import

# this is a special import block (and this comment ends up
# in arguably the wrong place!)
import foo.bar.baz


def f():
    """Calls some stuff in foo, mwahaha!"""
    foo.bar.baz.some_function()
    foo.secrets.lulz()
