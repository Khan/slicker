"""File docstring mentioning that we depend on quux.mod.some_function.

Also mentions quux.mod.some_function in the body, for good measure.  FYI: the
function comes from quux/mod.py.
"""
import quux.mod as al


def f():
    # References quux.mod.some_function from quux/mod.py, here called
    # al.some_function.
    al.some_function('al.some_'
                      """function,
                      other_function""")
    al.some_function("super wacky al." 'some_'
                      """function,
                      other_function""")
