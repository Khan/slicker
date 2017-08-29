import foo.bar.baz


def f():
    x = (foo
         .bar
         .baz
         .some_function
         ())
    return (foo.
            bar.
            baz.
            some_function(
                x))
