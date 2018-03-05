"""Classes and functions relating to slicker's model of files.

Much of slicker doesn't operate directly on the AST; rather it operates on
higher-level concepts like imports and the names they provide.  This file
defines the classes representing those, and functions for working with them.
"""
from __future__ import absolute_import

import ast
import collections

from . import util


class Import(object):
    """An import in the file (or a part thereof, if commas are used).

    Properties:
        name: the fully-qualified symbol we imported.
        alias: the name under which we imported it.
        relativity: 'absolute', 'explicit', or 'implicit', depending whether
            the import is absolute ('from slicker import util'), explicitly
            relative ('from . import util'), or implicitly relative (just
            'import util').  At present the latter is unused as we don't handle
            those imports.
            TOOD(benkraft): Handle implicit relative imports.
        node: the AST node for the import.  None for imports we will create.
        file_info: the util.FileInfo for the file in which the import resides
            (or will reside).

    So for example, 'from foo import bar' would result in an Import with
    name='foo.bar' and alias='bar'.  See test cases for more examples.  Note
    that for relative imports, 'name' will be the real, absolute name.
    """
    def __init__(self, name, alias, relativity, node, file_info):
        # TODO(benkraft): Should relativity/node be optional?
        # TODO(benkraft): Perhaps this class should also own extracting
        # name/alias from node.
        self.name = name
        self.alias = alias
        self.relativity = relativity
        self.node = node
        self._file_info = file_info
        self._span = None  # computed lazily

    @property
    def span(self):
        """Character offsets of the import; returns (startpos, endpos)."""
        if self._span is None:
            self._span = self._file_info.tokens.get_text_range(self.node)
        return self._span

    @property
    def start(self):
        return self.span[0]

    @property
    def end(self):
        return self.span[1]

    def import_stmt(self):
        """Construct an import statement for this import.

        Most useful when node is None; otherwise you just want
        file_info.body[self.start:self.end].
        """
        # TODO(csilvers): properly handle the case that
        # name is "module.symbol" and alias is not None.
        if self.relativity == 'explicit':
            module_name_parts = util.module_name_for_filename(
                self._file_info.filename).split('.')
            import_name_parts = self.name.split('.')
            # Strip off the shared prefix.
            while import_name_parts[0] == module_name_parts[0]:
                import_name_parts.pop(0)
                module_name_parts.pop(0)

            # Level is in the same sense the ast means it: the number of dots
            # at the front of the 'from' part.
            level = len(module_name_parts)
            # The base is some dots, plus all the non-shared parts except the
            # last, which becomes the suffix.
            base = '.' * level + '.'.join(import_name_parts[:-1])
            suffix = import_name_parts[-1]

            if self.alias == suffix:
                return 'from %s import %s' % (base, self.alias)
            else:
                return 'from %s import %s as %s' % (base, suffix, self.alias)

        elif self.alias and self.alias != self.name:
            if '.' in self.name:
                base, suffix = self.name.rsplit('.', 1)
                if self.alias == suffix:
                    return 'from %s import %s' % (base, suffix)
            return 'import %s as %s' % (self.name, self.alias)

        else:
            return 'import %s' % self.name

    def __repr__(self):
        return "Import(name=%r, alias=%r)" % (self.name, self.alias)

    def __hash__(self):
        # self._span is computed from the other properties so we exclude it.
        return hash((self.name, self.alias, self.node, self._file_info))

    def __eq__(self, other):
        # self._span is computed from the other properties so we exclude it.
        return (isinstance(other, Import) and self.name == other.name
                and self.alias == other.alias and self.node == other.node
                and self._file_info == other._file_info)


# LocalName: how a particular name (symbol or module) is referenced
#            in the current file.
#   fullname: the fully-qualified name we are looking for
#   localname: the localname for this name in the current file
#   imp: the Import that makes this name available (if "name" is for
#        a module, then the import not only makes the name available,
#        it *is* the name! [except in weird cases]); can also be None
#        if we are operating on the file this name was defined in.
# So in the above example, if we were searching for foo.bar.some_function
# in a file that had 'from foo import bar', we'd get a LocalName
# with name='foo.bar.some_function' and localname='bar.some_function'.
#  See test cases for more examples.
# TODO(benkraft): It's super confusing that both the tuple and its
# .localname are called the "localname" -- see for example
# _localnames_from_localnames.  Rename to something bettter.
LocalName = collections.namedtuple(
    'LocalName', ['fullname', 'localname', 'imp'])


def compute_all_imports(file_info, within_node=None, toplevel_only=False):
    """Return info about the imports in this file.

    If node is passed, only return imports within that node.  If toplevel_only
    is truthy, look only at imports at the toplevel of the module -- not inside
    if, functions, etc.  (We don't support setting both at once.)  Otherwise,
    look at the whole file.

    Returns a set of Import objects.  We ignore __future__ imports.
    """
    imports = set()
    within_node = within_node or file_info.tree
    nodes = within_node.body if toplevel_only else ast.walk(within_node)
    for node in nodes:
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            if isinstance(node, ast.ImportFrom):
                if node.module == '__future__':
                    continue
                elif node.level != 0:
                    # The notable "weird" case here is e.g.
                    # "from ... import sys", where full_from will be '', is
                    # technically legal, albeit discouraged.
                    # cf. https://www.python.org/dev/peps/pep-0328/
                    relative_to = '.'.join(
                        file_info.filename.split('/')[:-node.level])
                    relativity = 'explicit'
                    if node.module and relative_to:
                        # Covers "from .foo import bar"
                        full_from = '%s.%s' % (relative_to, node.module)
                    else:
                        # Covers both "from . import bar" and the weird case
                        # "from ...sys import path" mentioned above.
                        full_from = relative_to or node.module
                else:
                    full_from = node.module
                    relativity = 'absolute'
            else:
                full_from = ''
                relativity = 'absolute'

            for alias in node.names:
                if full_from:
                    name = '%s.%s' % (full_from, alias.name)
                else:
                    name = alias.name

                imports.add(
                    Import(name, alias.asname or alias.name,
                           relativity, node, file_info))

    return imports


def _import_provides_module(imp, module):
    """Return whether this import could possibly give access to this module.

    If module is 'foo.bar' this would return True for 'import foo.bar',
    'from foo import bar', and 'import foo.baz' -- the last is the
    "implicit imports" case mentioned in the file docstring.

    Arguments:
        imp: an Import object
        module: the fullname of a module.
    """
    if imp.name == module:
        # We are importing the module.
        return True
    elif imp.alias == imp.name:
        # There is no from/as: we need to check for "implicit imports".
        return imp.name.split('.', 1)[0] == module.split('.', 1)[0]
    return False


def localnames_from_fullnames(file_info, fullnames, imports=None):
    """Return LocalNames by which the fullnames may go in this file.

    If passed, we use the imports from 'imports', which should be a set
    of imports; otherwise we use all the imports from the file_info.

    Returns an iterable of LocalName namedtuples.

    See also _localnames_from_localnames, which returns more or less
    the same data, but starts from localnames instead of fullnames.

    For fullnames of symbols defined in this file, we include a
    LocalName(fullname, unqualified_name, None) because that's another way
    you can reference the fullname in this file.

    Note that 'import foo.baz' also makes 'foo.bar.myfunc' available
    (see module docstring, "implicit imports"), so we have to include
    that as well.  If you also did 'import foo.bar', we don't bother --
    we only include the "best" name when we can -- but if you did
    'from foo import bar' you you actually still have access to
    'foo.bar.myfunc' as both 'bar.myfunc' and 'foo.bar.myfunc' so we
    return a LocalName for each.  (Hopefully the latter is unused.)

    If a fullname is not made available by any import in this file,
    we won't return any corresponding LocalNames.  It might seem
    like this set should always have at most one LocalName for
    each fullname, but there are several cases it might have more:
    1) In the "implicit imports" case mentioned above.
    2) If you import a module two ways or from itself (see special
       cases (3) and (4) in the module docstring).
    4) If you do several "late imports" (see module docstring),
       you'll get one return-value per late-import that you do.
    """
    if imports is None:
        imports = compute_all_imports(file_info)
    current_module_name = util.module_name_for_filename(file_info.filename)

    imports_by_name = {}
    unaliased_imports_by_name_prefix = {}
    for imp in imports:
        name_prefix = imp.name.split('.', 1)[0]
        imports_by_name.setdefault(imp.name, []).append(imp)
        if imp.name == imp.alias:
            unaliased_imports_by_name_prefix.setdefault(
                name_prefix, []).append(imp)

    for fullname in fullnames:
        found_explicit_unaliased_import = False
        for fullname_prefix in util.dotted_prefixes(fullname):
            if fullname_prefix in imports_by_name:
                for imp in imports_by_name[fullname_prefix]:
                    yield LocalName(fullname,
                                    imp.alias + fullname[len(imp.name):], imp)
                    if imp.alias == imp.name:
                        found_explicit_unaliased_import = True

        if not found_explicit_unaliased_import:
            # This deals with the case where you did 'import foo.bar' and then
            # used 'foo.baz' -- an "implicit import".
            implicit_imports = unaliased_imports_by_name_prefix.get(
                fullname.split('.', 1)[0], [])
            for imp in implicit_imports:
                yield LocalName(fullname, fullname, imp)

        # If the name is a specific symbol defined in the file on which we are
        # operating, we also treat the unqualified reference as a localname,
        # with null import.
        if (util.dotted_starts_with(fullname, current_module_name)
                and fullname != current_module_name):
            # Note that in this case localnames is likely empty if we get here,
            # although it's not guaranteed since python lets you do `import
            # foo.bar` in foo/bar.py, at least in some cases.
            unqualified_name = fullname[len(current_module_name) + 1:]
            yield LocalName(fullname, unqualified_name, None)


def localnames_from_localnames(file_info, localnames, imports=None):
    """Return LocalNames by which the localnames may go in this file.

    That is, given some string-localnames, like 'bar', return some
    LocalName tuples, like `LocalName('foo.bar', 'bar', <Import object>)`
    corresponding to them.  (So for each input localname the corresponding
    output tuple(s) will have that localname as tuple.localname.)

    If passed, we use the imports from 'imports', which should be a set
    of imports; otherwise we use all the imports from the file_info.

    Returns an iterable of LocalName namedtuples.

    See also model.localnames_from_fullnames, which returns more or less
    the same data, but starts from fullnames instead of localnames.

    If the unqualified name of a symbol defined in this file
    appears in localnames, the corresponding LocalName will be
    LocalName(fullname, unqualified_name, None).

    Note that 'import foo.baz' also makes 'foo.bar.myfunc' available
    (see module docstring, "implicit imports"), so so we have to include
    that as well.  If you also did 'import foo.bar', we don't bother --
    we only include the "best" name when we can.  (We make this choice
    per-localname, so if you did 'import foo.baz' and
    'from foo import bar', and localnames is {'foo.bar.myfunc',
    'bar.myfunc'}, we'll return the quirky LocalName for
    'foo.bar.myfunc' as well as the more normal one for 'bar.myfunc'.

    If a fullname is not made available by any import in this file,
    we won't return any corresponding LocalNames.  It might seem
    like this set should always have at most one LocalName for
    each fullname, but there are several cases it might have more:
    1) In the "quirk of python" case mentioned above.
    2) If you import a module two ways or from itself (see special
       cases (3) and (4) in the module docstring).
    4) If you do several "late imports" (see module docstring),
       you'll get one return-value per late-import that you do.

    If a localname is not made available by any import in this file,
    we won't return any corresponding LocalNames -- perhaps it's
    actually a local variable.  It might seem like this set
    should always have at most one LocalName for each localname,
    but there are several cases it might have more:
    1) If there are multiple "implicit imports" as mentioned above.
    2) If you do several "late imports" (see module docstring),
       you'll get one return-value per late-import that you do.
    3) If the localname is defined in this file, and the file also
       imports itself (special case (4) in the module docstring).
    """
    # TODO(benkraft): Share code with model.localnames_from_fullnames, they do
    # similar things.
    if imports is None:
        imports = compute_all_imports(file_info)
    current_module_name = util.module_name_for_filename(file_info.filename)
    toplevel_names = util.toplevel_names(file_info)

    imports_by_alias = {}
    imports_by_alias_prefix = {}
    for imp in imports:
        alias_prefix = imp.alias.split('.', 1)[0]
        imports_by_alias.setdefault(imp.alias, []).append(imp)
        imports_by_alias_prefix.setdefault(alias_prefix, []).append(imp)

    for localname in localnames:
        found_explicit_import = False
        for localname_prefix in util.dotted_prefixes(localname):
            if localname_prefix in imports_by_alias:
                for imp in imports_by_alias[localname_prefix]:
                    yield LocalName(imp.name + localname[len(imp.alias):],
                                    localname, imp)
                found_explicit_import = True

        if not found_explicit_import:
            # This deals with the case where you did 'import foo.bar' and then
            # used 'foo.baz' -- an "implicit import".
            implicit_imports = imports_by_alias_prefix.get(
                localname.split('.', 1)[0], [])
            for imp in implicit_imports:
                yield LocalName(localname, localname, imp)

        # If the name is a specific symbol defined in the file on which we are
        # operating, we also treat the unqualified reference as a localname,
        # with null import.
        for toplevel_name in toplevel_names:
            if util.dotted_starts_with(localname, toplevel_name):
                yield LocalName('%s.%s' % (current_module_name, toplevel_name),
                                toplevel_name, None)
                break
