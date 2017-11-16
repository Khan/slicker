"""File docstring mentioning that we depend on foo.some_function.

Also mentions foo.some_function in the body, for good measure.  FYI: the
function comes from foo.py.
"""
import foo as baz


def f():
    # References foo.some_function from foo.py, here called
    # baz.some_function.
    baz.some_function('baz.some_'
                      """function,
                      other_function""")
    baz.some_function("super wacky baz." 'some_'
                      """function,
                      other_function""")
