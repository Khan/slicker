import foo.baz  # should update this, for the call in g(), but we don't


def f():
    import quux
    quux.some_function()


def g():
    quux.some_function()
    foo.baz.other_function()


def h():
    import quux
    quux.some_function()
