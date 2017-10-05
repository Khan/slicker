import baz
import foo.bar
import foo.baz
import foo.foobar


def f():
    foo.bar.asdf()
    foo.baz.something(baz.replaced, foo.foobar.the_foobar)
