import foo.baz  # should update this, for the call in g(), but we don't


def f():
    import foo.bar
    foo.bar.some_function()


def g():
    foo.bar.some_function()
    foo.baz.other_function()


def h():
    import foo.bar
    foo.bar.some_function()
