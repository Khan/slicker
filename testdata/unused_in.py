# this is a special import block:
import foo.bar
import foo.baz  # @UnusedImport


def f():
    foo.bar.some_function()  # needs foo.bar to be imported
