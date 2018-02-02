slicker: a tool for moving python files
---------------------------------------

If you've ever tried to move a function or class in python, you'll find it's
kind of a pain: you have to not only move the definition (and its imports,
etc.) but also update references across the codebase.  Slicker is a tool for
doing just that!

## Installation

`pip install slicker`

## Usage

To move a function `myfunc` defined in `foo/bar.py` to `foo/baz.py`:
```
slicker.py foo.bar.myfunc foo.baz.myfunc
```

The same syntax works if `myfunc` is instead a constant or class (although I
sure hope you didn't name a class `myfunc`!).  It also works if you want to
change the name of `myfunc`:
```
slicker.py foo.bar.myfunc foo.bar.new_name_for_myfunc
```
(And you can also make both changes at once, in the natural way.)

To move an entire module `foo/bar.py` to `foo/baz.py` you can do similarly:
```
slicker.py foo.bar foo.baz
```
or use filenames like:
```
slicker.py foo/bar.py foo/baz.py
```

You can also move a symbol into an existing module, or a module into an
existing directory, just like `mv`.  So this is equivalent to the first
example:
```
slicker.py foo.bar.myfunc foo.baz
```
And to move `foo/bar.py` to a new file `newfoo/bar.py` in an existing directory
`newfoo/`, you could do
```
slicker.py foo.bar newfoo  # (or slicker.py foo/bar.py newfoo/)
```
Using this syntax, you can also specify multiple things to move, so you could
move both `foo/bar.py` and `foo/baz.py` to `newfoo/` with
```
slicker.py foo/bar.py foo/baz.py newfoo/
```

You can tell slicker to use an alias when adding imports using `-a`/`--alias`:
```
slicker.py foo.bar.myfunc foo.baz.myfunc --alias baz
```
in which case slicker will add `from foo import baz` everywhere instead of
`import foo.baz`.  (You could also have used `--alias foobaz` in which case
we would have done `import foo.baz as foobaz`.)

If you prefer to move the actual definition yourself, and just have slicker
update the references, you can pass `--no-automove`.  It's probably best to run
`slicker` after doing said move.

For a full list of options, run `slicker.py --help`.


## Frequently and Infrequently Asked Questions

### What does slicker mean if it says "This import may be used implicitly."?

If you do `import foo.bar`, and some other file (perhaps another one you
import) does `import foo.baz`, then your `foo` now also has a `foo.baz`, and so
you can do `foo.baz.func()` with impunity, even though no import in your file
directly mentions that module.  (This is because `foo` in both files refers to
the same object -- a.k.a.  `sys.modules['foo']` -- and so when the other file
does `import foo.baz` it attaches `baz` to that shared object.)  So if you've
asked slicker to move `foo.bar` to `newfoo.bar`, when updating this file, it
would like to replace the `import foo.bar` with `import newfoo.bar`, but it
can't -- you're actually still using the import.  So it will warn you of this
case, and let you sort things out by hand.

### Slicker left me with a bunch of misindented or long lines!

Yep, we don't fix these correctly (yet).  Your linter should tell you what to
fix, though.

### Why is it called slicker?

Because pythons slither to move around, but this way is, uh, slicker.  Which is
to say: it seemed like a good idea at the time and as far as I could tell the
name wasn't already taken.

### How does it work?

Read the source!  Or bug the authors to write a blog post about it :-) .

### Why don't you just use [PyCharm](https://www.jetbrains.com/pycharm/) or [rope](https://github.com/python-rope/rope)?

Good question -- we tried!  Both are great projects and do a lot of things
slicker doesn't; if they work for you then definitely use them.  But for us,
they aren't quite as detailed in what they do, so they didn't fix up everything
quite right for us, and they're not particularly configurable (e.g. to conform
to KA style) or hackable (due to how general they try to be).  We were more
interested in a tool that would do one thing really well.  For more details,
bug the authors to write that blog post!

### Why don't you just use `codemod` or `sed`/`perl`?

Good question -- we tried!  But it takes a lot of gluing things together to
figure out all the right references to fix up in each file.  And there's
basically no hope of doing the right thing when fixing up string-references.
We needed something that knew what python imports mean and could handle their
special cases.
