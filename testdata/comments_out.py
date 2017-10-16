"""File docstring mentioning that we depend on quux.mod.some_function.

Also mentions quux.mod.some_function in the body, for good measure.
"""
import quux.mod as al


def f():
    # References quux.mod.some_function, here called al.some_function.
    al.some_function("""al.some_function,
                      other_function""")
    al.some_function("super wacky " """al.some_function,
                      other_function""")
