import foo.baz  # should update this, for the call in g(), but we don't


def f():
    # NOTE(benkraft): Here and below, we don't order things right due to
    # limitations of fix_python_imports (it doesn't deal with late imports).
    # Additionally, here, we don't notice that we can remove foo.bar, because
    # we don't chase scopes.
    import foo.bar
    foo.bar.some_function()


def g():
    foo.bar.some_function()
    foo.baz.other_function()


def h():
    import foo.bar
    foo.bar.some_function()
    foo.bar.other_function()
