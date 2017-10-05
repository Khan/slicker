import foo.bar
import foo.baz
import foo.foobar
from foo import quux


def f():
    foo.bar.asdf()
    foo.baz.something(quux.replaceme, foo.foobar.the_foobar)
