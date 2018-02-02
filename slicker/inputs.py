"""Function for converting the input fullnames to a canonical form.

We support many types of inputs:
    . renaming a symbol in a module to another symbol in a different module
    . renaming a module to another name
    . moving a module to another package
    . moving multiple modules to other packages
    . renaming a package to another name
    . moving a package to be a sub-package of some existing package
    . renaming a file to another file
    . renaming a directory to another directory
    . moving a file from one directory to another
    . moving a directory from one directory to another
    . and more!

This is the function that takes the inputs of all these different
forms and converts them to one of only two types of moves:
    . Move a module from one name to another
    . Move a symbol from one name to another

It also does sanity-checking of the inputs, to make sure they refer
to real objects.
"""
from __future__ import absolute_import

import os

from . import khodemod
from . import util


def _expand_and_normalize_one(project_root, old_fullname, new_fullname,
                              path_filter=khodemod.default_path_filter()):
    """See expand_and_normalize.__doc__."""
    def filename_for(mod):
        return os.path.join(project_root, util.filename_for_module_name(mod))

    def _assert_exists(module, error_prefix):
        if not os.path.exists(filename_for(module)):
            raise ValueError("%s: %s not found"
                             % (error_prefix, filename_for(module)))

    def _normalize_fullname_and_get_type(fullname):
        # Check the cases that fullname is a file or a directory.
        # We convert it to a module if so.
        if fullname.endswith('.py'):
            relpath = os.path.relpath(fullname, project_root)
            return (util.module_name_for_filename(relpath), "module")
        if os.sep in fullname:
            relpath = os.path.relpath(fullname, project_root)
            return (util.module_name_for_filename(relpath), "package")

        if os.path.exists(filename_for(fullname)):
            return (fullname, "module")
        if os.path.exists(filename_for(fullname + '.__init__')):
            return (fullname, "package")

        # If we're foo.bar, we could be a symbol named bar in foo.py
        # or we could be a file foo/bar.py.  To distinguish, we check
        # if foo/__init__.py exists.
        if '.' in fullname:
            (parent, symbol) = fullname.rsplit('.', 1)
            if os.path.exists(filename_for(parent + '.__init__')):
                return (fullname, "module")
            if os.path.exists(filename_for(parent)):
                return (fullname, "symbol")

        return (fullname, "unknown")

    def _modules_under(package_name):
        """Yield module-names relative to package_name-root."""
        package_dir = os.path.dirname(filename_for(package_name + '.__init__'))
        for path in khodemod.resolve_paths(path_filter, root=package_dir):
            yield util.module_name_for_filename(path)

    (old_fullname, old_type) = _normalize_fullname_and_get_type(old_fullname)
    (new_fullname, new_type) = _normalize_fullname_and_get_type(new_fullname)

    if old_fullname == new_fullname:
        raise ValueError("Cannot move an object (%s) to itself" % old_fullname)

    # Below, we follow the following rule: if we don't know what
    # the type of new_type is (because it doesn't exist yet), we
    # assume the user wanted it to be the same type as old_type.

    if old_type == "symbol":
        (module, symbol) = old_fullname.rsplit('.', 1)
        _assert_exists(module, "Cannot move %s" % old_fullname)

        # TODO(csilvers): check that the 2nd element of the return-value
        # doesn't refer to a symbol that already exists.
        if new_type == "symbol":
            yield (old_fullname, new_fullname, True)
        elif new_type == "module":
            yield (old_fullname, '%s.%s' % (new_fullname, symbol), True)
        elif new_type == "package":
            raise ValueError("Cannot move symbol '%s' to a package (%s)"
                             % (old_fullname, new_fullname))
        elif new_type == "unknown":
            # According to the rule above, we should treat new_fullname
            # as a symbol.  But if it doesn't have a dot, it *can't* be
            # a symbol; symbols must look like "module.symbol".  So we
            # assume it's a module instead.
            if "." in new_fullname:
                yield (old_fullname, new_fullname, True)
            else:
                yield (old_fullname, '%s.%s' % (new_fullname, symbol), True)

    elif old_type == "module":
        _assert_exists(old_fullname, "Cannot move %s" % old_fullname)
        if new_type == "symbol":
            raise ValueError("Cannot move a module '%s' to a symbol (%s)"
                             % (old_fullname, new_fullname))
        elif new_type == "module":
            if os.path.exists(filename_for(new_fullname)):
                raise ValueError("Cannot use slicker to merge modules "
                                 "(%s already exists)" % new_fullname)
            yield (old_fullname, new_fullname, False)
        elif new_type == "package":
            module_basename = old_fullname.rsplit('.', 1)[-1]
            if os.path.exists(filename_for(new_fullname)):
                raise ValueError("Cannot move module '%s' into '%s': "
                                 "'%s.%s' already exists"
                                 % (old_fullname, new_fullname,
                                    new_fullname, module_basename))
            yield (old_fullname, '%s.%s' % (new_fullname, module_basename),
                   False)
        elif new_type == "unknown":
            yield (old_fullname, new_fullname, False)

    elif old_type == "package":
        _assert_exists(old_fullname + '.__init__',
                       "Cannot move %s" % old_fullname)
        if new_type in ("symbol", "module"):
            raise ValueError("Cannot move a package '%s' into a %s (%s)"
                             % (old_fullname, new_type, new_fullname))
        elif new_type == "package":
            if new_fullname.startswith(old_fullname + '.'):
                raise ValueError("Cannot move a package '%s' to its own "
                                 "subdir (%s)" % (old_fullname, new_fullname))
            if os.path.exists(filename_for(new_fullname + '.__init__')):
                # mv semantics, same as if we did 'mv /var/log /etc'
                package_basename = old_fullname.rsplit('.', 1)[-1]
                new_fullname = '%s.%s' % (new_fullname, package_basename)
                if os.path.exists(filename_for(new_fullname)):
                    raise ValueError("Cannot move package '%s': "
                                     "'%s' already exists"
                                     % (old_fullname, new_fullname))
            for module in _modules_under(old_fullname):
                yield ('%s.%s' % (old_fullname, module),
                       '%s.%s' % (new_fullname, module),
                       False)
        elif new_type == "unknown":
            for module in _modules_under(old_fullname):
                yield ('%s.%s' % (old_fullname, module),
                       '%s.%s' % (new_fullname, module),
                       False)

    elif old_type == "unknown":
        raise ValueError("Cannot figure out what '%s' is: "
                         "module or package not found" % old_fullname)


def expand_and_normalize(project_root, old_fullnames, new_fullname,
                         path_filter=khodemod.default_path_filter()):
    """Return a list of old-new-info triples that effect the requested rename.

    In the simple case old_fullname is a module and new_fullname is a
    module, this will just return the input: [(old_fullname,
    new_fullname)].  Likewise if old_fullname is a symbol and
    new_fullname is a symbol.

    But if old_fullname is a package (dir) and so is new_fullname,
    then we will return a list of (old_module, new_module, is_symbol)
    triples for every module under the dir.

    We also handle cases where old_fullname and new_fullname are not
    of the same "type", and where new_fullname already exists.  For
    instance, when moving a module into a package, we convert
    new_fullname to have the right name in the destination package.
    And when moving a package into a directory that already exists,
    we'll make it a subdir of the target-dir.

    We *also* handle cases where old_fullname and new_fullname are
    files instead of dotted module names.  In that case we convert
    them to module-names first.

    When moving a symbol to a module, a module to a package, or a
    package into a new directory, you can have several inputs, and
    each will be moved.

    Some types of input are illegal: it's probably a mistake if
    old_fullname is a symbol and new_fullname is a package.  Or
    if old_fullname doesn't actually exist.  We raise in those cases.

    Returns:
       (old_fullname, new_fullname, is_symbol) triples.
       is_symbol is true if old_fullname is a symbol in a module, or
       false if it's a module.
    """
    retval = []
    for old_fullname in old_fullnames:
        retval.extend(_expand_and_normalize_one(project_root, old_fullname,
                                                new_fullname, path_filter))

    # Sanity-check.  If two different things are being moved to the
    # same new-fullname, that's a problem.  It probably means we tried
    # to move two modules into a module instead of into a package, or
    # some such.
    seen_newnames = {}
    for (old_fullname, new_fullname, _) in retval:
        if new_fullname in seen_newnames:
            raise ValueError(
                "You asked to rename both '%s' and '%s' to '%s'. Impossible!"
                % (old_fullname, seen_newnames[new_fullname], new_fullname))
        seen_newnames[new_fullname] = old_fullname

    return retval
