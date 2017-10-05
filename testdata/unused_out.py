# this is a special import block:
import foo.baz  # @UnusedImport
import quux


def f():
    quux.some_function()  # needs foo.bar to be imported
