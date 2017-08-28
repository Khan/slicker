# does stuff
import foo.bar.baz  # STOPSHIP: This import may be used implicitly.
import quux


def f():
    """Calls some stuff in foo, mwahaha!"""
    quux.new_name()
    foo.secrets.lulz()
