"""File docstring mentioning that we depend on foo.bar.some_function.

Also mentions foo.bar.some_function in the body, for good measure.
"""
import foo.bar as baz


def f():
    # References foo.bar.some_function, here called baz.some_function.
    baz.some_function('baz.some_'
                      """function,
                      other_function""")
    baz.some_function("super wacky baz." 'some_'
                      """function,
                      other_function""")
