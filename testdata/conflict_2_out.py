# STOPSHIP: Your alias will conflict with the following imports:
#    quux
# Not touching this file.
import quux as foo
import bar


def f():
    foo.boring_function()
    bar.interesting_function()
