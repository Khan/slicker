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

import os

import khodemod


# TODO(csilvers): break these out into some utility file?
def _filename_for_module_name(module_name):
    """filename is relative to a sys.path entry, such as your project-root."""
    return '%s.py' % module_name.replace('.', os.sep)


def _module_name_for_filename(filename):
    """filename is relative to a sys.path entry, such as your project-root."""
    return os.path.splitext(filename)[0].replace(os.sep, '.')


def expand_and_normalize(project_root, old_fullname, new_fullname,
                         frontend, path_filter=khodemod.default_path_filter()):
    """Yield a list of old-new-info triples that effect the requested rename.

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
    them to module-names first.  TODO(csilvers): implement this.

    When moving a module to a package, or a package into a new
    directory, you can have several inputs, and each will be moved.
    TODO(csilvers): implement this.

    Some types of input are illegal: it's probably a mistake if
    old_fullname is a symbol and new_fullname is a package.  Or
    if old_fullname doesn't actually exist.  We raise in those cases.

    Yields:
       (old_fullname, new_fullname, is_symbol) triples.
       is_symbol is true if old_fullname is a symbol in a module, or
       false if it's a module.

    """
    def filename_for(mod):
        return os.path.join(project_root, _filename_for_module_name(mod))

    def _fullname_type(fullname):
        if os.path.exists(filename_for(fullname)):
            return "module"
        if os.path.exists(filename_for(fullname + '.__init__')):
            return "package"
        if os.path.exists(filename_for(fullname.rsplit('.', 1)[0])):
            return "symbol"
        return "unknown"

    def _modules_under(package_name):
        """Yield module-names relative to package_name-root."""
        package_dir = os.path.dirname(filename_for(package_name + '.__init__'))
        for path in frontend.resolve_paths(path_filter, root=package_dir):
            yield _module_name_for_filename(path)

    old_type = _fullname_type(old_fullname)
    new_type = _fullname_type(new_fullname)

    # Below, we follow the following rule: if we don't know what
    # the type of new_type is (because it doesn't exist yet), we
    # assume the user wanted it to be the same type as old_type.

    if old_type == "symbol":
        if new_type in ("symbol", "unknown"):
            yield (old_fullname, new_fullname, True)
        elif new_type == "module":
            symbol = old_fullname.rsplit('.', 1)
            # TODO(csilvers): check new_fullname doesn't already define
            # a symbol named `symbol`.
            yield (old_fullname, '%s.%s' % (new_fullname, symbol), True)
        elif new_type == "package":
            raise ValueError("Cannot move symbol '%s' to a package (%s)"
                             % (old_fullname, new_fullname))

    elif old_type == "module":
        if new_type == "symbol":
            raise ValueError("Cannot move a module '%s' to a symbol (%s)"
                             % (old_fullname, new_fullname))
        elif new_type == "module":
            raise ValueError("Cannot use slicker to merge modules "
                             "(%s already exists)" % new_fullname)
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
        if new_type in ("symbol", "module"):
            raise ValueError("Cannot move a package '%s' into a %s (%s)"
                             % (old_fullname, new_type, new_fullname))
        elif new_type == "package":
            package_basename = old_fullname.rsplit('.', 1)[-1]
            # mv semantics, same as if we did 'mv /var/log /etc'
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
