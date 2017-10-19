# does stuff
import foo.bar.baz
import foo.public
import quux


def f():
    """Calls some stuff in foo, mwahaha!"""
    foo.bar.baz.some_function()
    foo.public.function()
    quux.new_name()
