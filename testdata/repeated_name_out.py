import bar.foo.foo


def test():
    with mock.patch('bar.foo.foo.myfunc', lambda: None):
        pass
    bar.foo.foo.otherfunc(bar.foo.foo)
