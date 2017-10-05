# STOPSHIP: Your alias will result in import conflicts for these symbols:
#    foo.boring_function
# Please fix the imports in this file manually.
import foo


def f():
    foo.boring_function()
    foo.interesting_function()
