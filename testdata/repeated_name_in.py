from foo import foo

def test():
    with mock.patch('foo.foo.myfunc', lambda: None):
        pass
    foo.otherfunc(foo)
