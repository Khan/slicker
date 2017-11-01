from __future__ import absolute_import

import foo.bar.baz
# this is a special import block (and this comment ends up
# in arguably the wrong place!)
import quux


def f():
    """Calls some stuff in foo, mwahaha!"""
    quux.new_name()
    foo.secrets.lulz()
