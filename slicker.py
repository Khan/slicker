#!/usr/bin/env python

"""A tool to move python modules and/or symbols and fix up all references.

Renaming a file (aka module) in python is non-trivial: you not only
need to rename the file, you need to find all other files that import
you and fix up their imports.  And if code refers to your file in a
string (e.g. for mocking) you need to fix that up too.  Slicker is a
tool to help with that: it will rename the file and fix up references
in code, strings, and comments.

But wait, there's more!  Slicker can also move individual top-level
symbols from one file to another.  (The destination file can be new.)
You can use this to "break up" files into smaller pieces, or just move
components that would better fit elsewhere.  The types of symbols that
can be moved are:
* top-level functions
* top-level classes
* top-level constants and variables


SPECIAL CASES IN PYTHON IMPORTS

One of the reasons slicker is complex is that python imports can do
a number of pathological things, if you're not careful.  Here are the
ones we have to deal with the most:
0) In addition to imports at the top of the file, there can be imports
   inside functions.  These are often used to avoid circular imports, or
   to avoid pulling in a module until it's certainly needed.  Often the
   same file will have several such imports of the same module, in
   different functions.  These aren't really a pathological case, just
   one that requires special handling in some places.  We call them
   "late imports".
1) If you do `import foo.bar`, and some other file (perhaps another one
   you import) does `import foo.baz`, then your `foo` now also has a
   `foo.baz`, and so you can do `foo.baz.func()` with impunity, even
   though no import in your file directly mentions that module.  (This
   is because `foo` in both files refers to the same object -- a.k.a.
   `sys.modules['foo']` -- and so when the other file does
   `import foo.baz` it attaches `baz` to that shared object.)  We call
   these "implicit imports", or say you accessed `foo.baz.func`
   "implicitly". Note that if you do `from foo import bar` this problem
   can't arise, as you don't have access to any `foo`.
2) Similarly, if you do `import foo` and some other file does
   `import foo.bar`, your foo now also has a `foo.bar`.  Slicker doesn't
   handle this case as well, as it's hard to tell whether `bar` is a
   symbol defined in `foo.py` (in which case this pattern is fine) or a
   module `foo/bar.py` (in which case it's not great).
3) Modules can import the same file in multiple ways.  For example, you
   might do both `import foo.bar` and `from foo import bar`, in which
   case `foo.bar.func` is available as both `foo.bar.func` and
   `bar.func`.  Hopefully you don't do that.
4) Modules can import themselves.  For example, `foo/bar.py` might do
   'import foo.bar`, in which case a function `func` defined in it is
   available as both `func` and `foo.bar.func`.  Hopefully you don't do
   that either.

TERMINOLOGY USED INTERNALLY

0) "late import", "implicit import": see special cases (0) and (1) above.
1) "fullname": the fully-qualified symbol or module being moved.  If you
   are moving class Importer from foo/bar.py to foo/baz.py, then
   the old "fullname" is foo.bar.Importer and the new "fullname" is
   foo.baz.Importer.
2) "localname": how the symbol-being-moved is referred to in the current
   file that we're analyzing.  If you're moving class Importer from
   foo/bar.py to foo/baz.py, and qux.py has a line:
       import foo.bar as foo_bar
   then the "localname" while processing qux.py is "foo_bar.Importer".
"""
from __future__ import absolute_import

import argparse
import ast
import collections
import difflib
import itertools
import os
import re
import sys
import tokenize

import fix_python_imports
import inputs
import khodemod
import moves
import util


def _re_for_name(name):
    """Find a dotted-name (a.b.c) given that Python allows whitespace.

    Note we check for *top-level* dotted names, so we would not match
    'd.a.b.c.'
    """
    # TODO(csilvers): replace '\s*' by '\s*#\s*' below, and then we
    # can use this to match line-broken dotted-names inside comments too!
    return re.compile(r'(?<!\.)\b%s\b' %
                      re.escape(name).replace(r'\.', r'\s*\.\s*'))


def _dotted_starts_with(string, prefix):
    """Like string.startswith(prefix), but in the dotted sense.

    That is, abc is a prefix of abc.de but not abcde.ghi.
    """
    return prefix == string or string.startswith('%s.' % prefix)


def _dotted_prefixes(string):
    """All prefixes of string, in the dotted sense.

    That is, all strings p such that _dotted_starts_with(string, p), in order
    from shortest to longest.
    """
    string_parts = string.split('.')
    for i in xrange(len(string_parts)):
        yield '.'.join(string_parts[:i + 1])


class FakeOptions(object):
    """A fake `options` object to pass in to fix_python_imports."""
    def __init__(self, project_root):
        self.safe_headers = True
        self.root = project_root


# Import: an import in the file (or a part thereof, if commas are used).
#   name: the fully-qualified symbol we imported.
#   alias: the name under which we imported it.
#   start, end: character-indexes delimiting the import
#   node: the AST node for the import.
# So for example, 'from foo import bar' would result in an Import with
# name='foo.bar' and alias='bar'.  If it were at the start of the file it
# would have start=0, end=19.  See test cases for more examples.
Import = collections.namedtuple(
    'Import', ['name', 'alias', 'start', 'end', 'node'])

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


def _compute_all_imports(file_info, within_node=None, toplevel_only=False):
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
            if isinstance(node, ast.ImportFrom) and node.level != 0:
                # TODO(benkraft): Handle these, now that we have access to the
                # filename we are operating on.
                continue
            start, end = file_info.tokens.get_text_range(node)
            for alias in node.names:
                if isinstance(node, ast.Import):
                    imports.add(
                        Import(alias.name, alias.asname or alias.name,
                               start, end, node))
                elif node.module != '__future__':
                    imports.add(
                        Import('%s.%s' % (node.module, alias.name),
                               alias.asname or alias.name, start, end, node))
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


def _localnames_from_fullnames(file_info, fullnames, imports=None):
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
        imports = _compute_all_imports(file_info)
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
        for fullname_prefix in _dotted_prefixes(fullname):
            if fullname_prefix in imports_by_name:
                for imp in imports_by_name[fullname_prefix]:
                    yield LocalName(fullname,
                                    imp.alias + fullname[len(imp.name):], imp)
                    if imp.alias != imp.name:
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
        if (_dotted_starts_with(fullname, current_module_name)
                and fullname != current_module_name):
            # Note that in this case localnames is likely empty if we get here,
            # although it's not guaranteed since python lets you do `import
            # foo.bar` in foo/bar.py, at least in some cases.
            unqualified_name = fullname[len(current_module_name) + 1:]
            yield LocalName(fullname, unqualified_name, None)


def _localnames_from_localnames(file_info, localnames, imports=None):
    """Return LocalNames by which the localnames may go in this file.

    That is, given some string-localnames, like 'bar', return some
    LocalName tuples, like `LocalName('foo.bar', 'bar', <Import object>)`
    corresponding to them.  (So for each input localname the corresponding
    output tuple(s) will have that localname as tuple.localname.)

    If passed, we use the imports from 'imports', which should be a set
    of imports; otherwise we use all the imports from the file_info.

    Returns an iterable of LocalName namedtuples.

    See also _localnames_from_fullnames, which returns more or less
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
    # TODO(benkraft): Share code with _localnames_from_fullnames, they do
    # similar things.
    if imports is None:
        imports = _compute_all_imports(file_info)
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
        for localname_prefix in _dotted_prefixes(localname):
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
        if localname in toplevel_names:
            yield LocalName('%s.%s' % (current_module_name, localname),
                            localname, None)


def _name_for_node(node):
    """Return the dotted name of an AST node, if there's a reasonable one.

    A 'name' is just a dotted-symbol, e.g. `myvar` or `myvar.mystruct.myprop`.

    This only does anything interesting for Name and Attribute, and for
    Attribute only if it's like a.b.c, not (a + b).c.
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        value = _name_for_node(node.value)
        if value:
            return '%s.%s' % (value, node.attr)


def _all_names(root):
    """All names in the file.

    A 'name' is just a dotted-symbol, e.g. `myvar` or `myvar.mystruct.myprop`.

    Does not include imports or string references or anything else funky like
    that, and only returns the "biggest" possible name -- if you reference
    a.b.c we won't include a.b.

    Returns pairs (name, node)
    """
    name = _name_for_node(root)
    if name:
        return {(name, root)}
    else:
        return {(name, node)
                for child in ast.iter_child_nodes(root)
                for name, node in _all_names(child)}


def _names_starting_with(prefix, ast_node):
    """Returns all dotted names in the given file beginning with 'prefix'.

    Does not include imports or string references or anything else funky like
    that.  "Beginning with prefix" in the dotted sense (see
    _dotted_starts_with).

    Returns a dict of name -> list of AST nodes.
    """
    retval = {}
    for name, node in _all_names(ast_node):
        if _dotted_starts_with(name, prefix):
            retval.setdefault(name, []).append(node)
    return retval


def _check_import_conflicts(file_info, added_name, is_alias):
    """Return any imports that will conflict with ours.

    Suppose our file says `from foo import bar as baz` and
    we want to add `import baz` (or `import qux as baz`).
    That's not going to work!  (Python allows it but one name
    will shadow the other.) Similarly if our file has
    `import baz.bang`.

    added_name should be the alias of the import, not the symbol.

    Returns a list of import objects.

    TODO(benkraft): If that's due to our alias, we could avoid using
    said alias.
    TODO(benkraft): We shouldn't consider it a conflict if the only
    user of the conflicting import is the moved symbol.
    TODO(benkraft): Also check if there are variable-names that
    collide.
    TODO(benkraft): Also check if there are names defined in the
    file that collide.
    """
    imports = _compute_all_imports(file_info)
    # TODO(csilvers): perhaps a more self-evident way to code this would
    # be: complain if there is any shared prefix between added_import.alias
    # and some_existing_import.alias.
    if is_alias:
        # If we are importing with an alias, we're looking for existing
        # imports with whose prefix we collide.
        # e.g. we're adding 'import foo.bar as baz' or 'from foo import baz'
        # and the existing code has 'import baz' or 'import baz.bang' or
        # 'from qux import baz' or 'import quux as baz'.
        return {imp for imp in imports
                if _dotted_starts_with(imp.alias, added_name)}
    else:
        # If we aren't importing with an alias, we're looking for
        # existing imports who are a prefix of us.
        # e.g. we are adding 'import foo' or 'import foo.bar' and the
        # existing code has 'import baz as foo' or 'from baz import foo'.
        # TODO(csilvers): this is actually ok in the case we're going
        # to remove the 'import baz as foo'/'from baz import foo' because
        # the only client of that import is the symbol that we're moving.
        return {imp for imp in imports
                if _dotted_starts_with(added_name, imp.alias)}


def _unused_imports(imports, file_info, within_node=None):
    """Decide what imports we can remove.

    Note that this should be run after the patches to references in the file
    have been applied, i.e. in a separate suggestor.

    Arguments:
        imports: set of imports to consider removing.  These should likely be
            the imports that got us the symbol whose references you're
            updating.
        file_info: the util.File object.
        within_node: if set, only consider imports within this AST node.
            (Useful for deciding whether to remove imports in that node.)

    Returns (set of imports we can remove,
             set of imports that may be used implicitly).

    "set of imports that may be used implicitly" is when we do
    "import foo.bar" and access "foo.baz.myfunc()" -- see
    special case (1) in the module docstring.
    """
    if within_node is None:
        within_node = file_info.tree
    # Decide whether to keep the old import if we changed references to it.
    unused_imports = set()
    implicitly_used_imports = set()
    used_imports = set()
    for imp in imports:
        # This includes all names that we might be *implicitly*
        # accessing via this import (special case (1) of the
        # module docstring, e.g. 'import foo.bar; foo.baz.myfunc()'.
        implicitly_used_names = _names_starting_with(
            imp.alias.split('.', 1)[0], within_node)
        # This is only those names that we are explicitly accessing
        # via this import, i.e. not via such an "implicit import".
        explicitly_referenced_names = [
            name for name in implicitly_used_names
            if _dotted_starts_with(name, imp.alias)]

        if explicitly_referenced_names:
            used_imports.add(imp)
        elif implicitly_used_names:
            implicitly_used_imports.add(imp)
        else:
            unused_imports.add(imp)

    # Now, if there was an import we were considering removing but which might
    # be used implicitly, and we are keeping a different import that gets us
    # the same things, we can remove the former.
    for maybe_removable_imp in list(implicitly_used_imports):
        prefix = maybe_removable_imp.alias.split('.')[0]
        for kept_imp in used_imports:
            if _dotted_starts_with(kept_imp.alias, prefix):
                implicitly_used_imports.remove(maybe_removable_imp)
                unused_imports.add(maybe_removable_imp)
                break

    return (unused_imports, implicitly_used_imports)


def _choose_best_localname(file_info, fullname, name_to_import, import_alias):
    """Decide what localname we should refer to fullname by in this file.

    If there's already an import of fullname, we'll use it.  If not, we'll
    choose the best import to add, based on name_to_import and import_alias.

    Returns: (the localname we should use,
              whether we need to add an import if we want to use it).

    (Note that if _choose_best_localname suggests to add an import, but the
    caller determines that we don't even need to add any references to this
    localname, said caller should likely ignore us and not add an import.)

    TODO(benkraft): Perhaps we should instead return the full text of the
    import we should add, if applicable?
    """
    # If name_to_import is already imported in this file,
    # figure out what the localname for our symbol would
    # be using this existing import.  That is, if we are moving
    # 'foo.myfunc' to 'bar.myfunc' and this file already has
    # 'import bar as baz' then existing_new_localnames would be
    # {'baz.myfunc'}.
    existing_new_localnames = {
        ln.localname
        for ln in _localnames_from_fullnames(file_info, {fullname})
        if ln.imp is None or name_to_import == ln.imp.name
    }

    if not existing_new_localnames:
        conflicting_imports = _check_import_conflicts(
            file_info, import_alias or name_to_import, bool(import_alias))
        if conflicting_imports:
            raise khodemod.FatalError(
                file_info.filename, conflicting_imports.pop().start,
                "Your alias will conflict with imports in this file.")

    if existing_new_localnames:
        # Prefer an existing explicit import to the caller-provided alias.
        # If for some reason there are multiple existing localnames
        # (unlikely), choose the shortest one, to save us line-wrapping.
        # TODO(benkraft): this might not be totally safe if the existing
        # import isn't toplevel, but probably it will be.
        return min(existing_new_localnames, key=len), False
    elif import_alias:
        return import_alias + fullname[len(name_to_import):], True
    else:
        return fullname, True


def _replace_in_string(str_tokens, regex, replacement, file_info):
    """Given a list of tokens representing a string, do a regex-replace.

    This is a bit tricky for a few reasons.  First, there may be
    multiple tokens that make up the string, with different
    delimiters, and spaces in between: `"I'm happy"\n'you liked it'`.
    Second, there may be escape sequences, which are annoying because
    the length of the symbol in the code (`\x2f`) is different than
    the length of the character in the string (`/`).  (While we don't
    support escape sequences in the regex itself we do want to be
    able to replace correctly if they're elsewhere in the string.)

    Arguments:
        str_tokens: a list of tokens corresponding to an ast.Str node
        regex: a compiled regex object
        replacement: a string to replace with (note we do not support \1-style
            references)
        file_info: the file to do the replacements in.

    Returns: a generator of khodemod.Patch objects.
    """
    str_tokens = [tok for tok in str_tokens if tok.type == tokenize.STRING]
    tokens_less_delims = []
    delims = []
    for token in str_tokens:
        if token.string.startswith('"""') or token.string.startswith("'''"):
            delims.append(token.string[:3])
            tokens_less_delims.append(token.string[3:-3])
        else:
            delims.append(token.string[:1])
            tokens_less_delims.append(token.string[1:-1])
    # Note that this still may have escapes in it; we just assume we can not
    # care (e.g. that identifiers are all ASCII)
    joined_unparsed_str = ''.join(tokens_less_delims)
    for match in regex.finditer(joined_unparsed_str):
        abs_start, abs_end = match.span()

        # Now convert the start and end of the match from an absolute
        # position in the string to a (token, pos-in-token) pair.
        start_within_token, end_within_token = abs_start, abs_end

        # Note:
        # 0 <= start_within_token < len(tokens_less_delims[start_token_index])
        # and 0 < end_within_token <= len(tokens_less_delims[end_token_index])
        for i, tok in enumerate(tokens_less_delims):
            if start_within_token < len(tok):
                start_token_index = i
                break
            else:
                start_within_token -= len(tok)
        for i, tok in enumerate(tokens_less_delims):
            if end_within_token <= len(tok):
                end_token_index = i
                break
            else:
                end_within_token -= len(tok)

        # Figure out what changes to actually make, based on the tokens we
        # have.
        deletion_start = (str_tokens[start_token_index].startpos +
                          len(delims[start_token_index]) + start_within_token)
        deletion_end = (str_tokens[end_token_index].startpos +
                        len(delims[end_token_index]) + end_within_token)

        # We're going to remove part (or possibly all) of start_token,
        # part (or possibly all) of end_token, and all the tokens in
        # between.  We need to combine what's left of start_token and
        # end_token into a single token.  That's annoying in the case
        # the two tokens use different delimiters (' vs ", say).
        # Though it's easy in the case we're deleting all of start_token
        # or all of end_token.

        if delims[start_token_index] == delims[end_token_index]:
            # Delimiters match, so we can just use the start-delimiter
            # from start_token and the end-delimiter from end_token.
            pass
        elif start_within_token == 0:
            # In this case, deletion_start would cause us to just keep
            # the start-delimiter from start_token, and delete the
            # rest.  Let's go all the way and delete *all* of
            # start-token, and add the start-delimiter back in to the
            # replacement text instead.  That way we can use the right
            # delimiter to match end_token's delimiter.
            deletion_start = str_tokens[start_token_index].startpos
            replacement = delims[end_token_index] + replacement
        elif end_within_token == len(tokens_less_delims[end_token_index]):
            # Same as above, except vice-versa.
            deletion_end = str_tokens[end_token_index].endpos
            replacement = replacement + delims[start_token_index]
        else:
            # We have to keep both tokens around, fixing delimiters and adding
            # space in between; likely the user will rewrap lines anyway.
            replacement = (
                delims[start_token_index] + ' ' + delims[end_token_index] +
                replacement)
        yield khodemod.Patch(
            file_info.filename,
            file_info.body[deletion_start:deletion_end], replacement,
            deletion_start, deletion_end)


def _replace_in_file(file_info, old_fullname, old_localnames,
                     new_fullname, new_localname, node_to_fix=None):
    """Replace old name with new name in file, everywhere.

    Arguments:
        old_fullname, new_fullname: as in _fix_uses_suggestor.
        old_localnames: the localnames to look for when replacing, as strings.
        new_localname: the localname to replace with, as a string.
        node_to_fix: if set, we only fix up references inside this AST node,
            rather than in the whole file.

    Returns (list of patches, set of old_localnames we found in code).  Note
    that the old_localnames we found in code may not all have been patched, in
    the case where new_localname was one of them.  (For example if you are
    moving 'foo.myfunc' to 'bar.myfunc' and had 'import foo as bar' in the old
    file.)  We return those anyway, since you may want to fix their imports.
    """
    patches = []
    used_localnames = set()
    node_to_fix = node_to_fix or file_info.tree

    # First, fix up normal references in code.
    for localname in old_localnames:
        for (name, ast_nodes) in (
                _names_starting_with(localname, node_to_fix).iteritems()):
            for node in ast_nodes:
                start, end = file_info.tokens.get_text_range(node)
                used_localnames.add(localname)
                if localname != new_localname:
                    patches.append(khodemod.Patch(
                        file_info.filename, file_info.body[start:end],
                        new_localname + name[len(localname):],
                        start, end))

    # Fix up references in strings and comments.  We look for both the
    # fully-qualified name (if it changed) and any aliases in use in this file,
    # as well as the filename if we are moving a module.  We always replace
    # fully-qualified references with fully-qualified references; references to
    # aliases get replaced with whatever we're using for the rest of the file.
    regexes_to_check = []
    # If we are just updating the localname, and not actually moving the symbol
    # -- which happens in _fix_moved_region_suggestor -- we don't need to
    # update references to the fullname, because it hasn't changed.
    if old_fullname != new_fullname:
        regexes_to_check.append((_re_for_name(old_fullname), new_fullname))
        # Also check for the fullname being represented as a file.
        # In cases where the fullname is not a module (but is instead
        # module.symbol) this will typically be a noop.
        regexes_to_check.append((
            re.compile(re.escape(util.filename_for_module_name(old_fullname))),
            util.filename_for_module_name(new_fullname)))
    for localname in old_localnames - {new_localname, old_fullname}:
        regexes_to_check.append((_re_for_name(localname), new_localname))

    # Strings
    for node in ast.walk(node_to_fix):
        if isinstance(node, ast.Str):
            str_tokens = list(
                file_info.tokens.get_tokens(node, include_extra=True))
            for regex, replacement in regexes_to_check:
                if regex.search(node.s):
                    patches.extend(
                        _replace_in_string(str_tokens,
                                           regex, replacement, file_info))

    # Comments
    for token in file_info.tokens.get_tokens(node_to_fix, include_extra=True):
        if token.type == tokenize.COMMENT:
            for regex, replacement in regexes_to_check:
                # TODO(benkraft): Handle names broken across multiple lines
                # of comments.
                for match in regex.finditer(token.string):
                    patches.append(khodemod.Patch(
                        file_info.filename,
                        match.group(0), replacement,
                        token.startpos + match.start(),
                        token.startpos + match.end()))

    return patches, used_localnames


def _new_import_stmt(name, alias=None):
    """Given a name and alias, decide the best import text.

    Returns an import statement, like 'from foo import bar'.
    """
    # TODO(csilvers): properly handle the case that
    # name is "module.symbol" and alias is not None.
    if '.' in name and alias:
        base, suffix = name.rsplit('.', 1)
        if alias == suffix:
            return 'from %s import %s' % (base, suffix)
        else:
            return 'import %s as %s' % (name, alias)
    else:
        if alias and alias != name:
            return 'import %s as %s' % (name, alias)
        else:
            return 'import %s' % name


def _add_contextless_import_patch(file_info, import_texts):
    """Add imports to the file_info, in a reasonable place.

    We use this in the case where there is no particular context to copy or
    point at which to place the import; we just want to guess something
    reasonable -- near existing imports if any.

    Arguments:
        file_info: the File object to add to.
        import_texts: a list of import statements as strings, like
            'from foo import bar'.

    Returns a patch.
    """
    joined_imports = ''.join(import_texts)
    last_toplevel_import = None
    for stmt in file_info.tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            last_toplevel_import = stmt

    if last_toplevel_import:
        start, end = util.get_area_for_ast_node(
            last_toplevel_import, file_info, include_previous_comments=False)
        return khodemod.Patch(
            file_info.filename, '', joined_imports, end, end)
    else:
        # There are no existing toplevel imports.  Find the first
        # place to add an import: after any comments, docstrings,
        # and newlines.  (*Not* after indents and the like!)
        # TODO(benkraft): We should really add before trailing
        # whitespace, but fix_pytnon_imports will mostly fix that.
        for tok in file_info.tokens.tokens:
            if not (tok.type == tokenize.COMMENT
                    or tok.type == tokenize.STRING
                    or util.is_newline(tok)):
                pos = tok.startpos
                break
        else:
            # The file has no code; add at the end.
            pos = len(file_info.body)

        # We add the absolute_import because KA style requires it.
        # (It's a good idea anyway.)
        text_to_add = (
            'from __future__ import absolute_import\n\n'
            '%s\n\n' % joined_imports)

        return khodemod.Patch(file_info.filename, '', text_to_add, pos, pos)


def _remove_import_patch(imp, file_info):
    """Remove the given import from the given file.

    Returns a khodemod.Patch, or a khodemod.WarningInfo if we can't/won't
    remove the import.
    """
    toks = list(file_info.tokens.get_tokens(imp.node, include_extra=False))
    next_tok = file_info.tokens.next_token(toks[-1], include_extra=True)
    if next_tok.type == tokenize.COMMENT and (
            '@nolint' in next_tok.string.lower() or
            '@unusedimport' in next_tok.string.lower()):
        # Don't touch nolinted imports; they may be there for a reason.
        # TODO(benkraft): Handle this case for implicit imports as well
        return khodemod.WarningInfo(
            file_info.filename, imp.start,
            "Not removing import with @Nolint.")
    elif ',' in file_info.body[imp.start:imp.end]:
        # TODO(benkraft): better would be to check for `,` in each
        # token so we don't match commas in internal comments.
        # TODO(benkraft): learn to handle this case.
        return khodemod.WarningInfo(
            file_info.filename, imp.start,
            "I don't know how to edit this import.")
    else:
        # TODO(benkraft): Should we look at preceding comments?
        # We end up fighting with fix_python_imports if we do.
        start, end = util.get_area_for_ast_node(
            imp.node, file_info, include_previous_comments=False)
        return khodemod.Patch(file_info.filename,
                              file_info.body[start:end], '', start, end)


# TODO(benkraft): Once slicker can do it relatively easily, move the
# use-fixing suggestors and helpers to their own file.
def _fix_uses_suggestor(old_fullname, new_fullname,
                        name_to_import, import_alias=None):
    """The suggestor to fix all references to a file or symbol.

    Note that this adds new imports for any references we updated, but does not
    remove the old ones; see _remove_imports_suggestor.

    Arguments:
        old_fullname: the pre-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.
        new_fullname: the post-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.
        name_to_import: the module or module.symbol we want to add to
            provide access to new_fullname.  (KA style is to disallow
            importing symbols explicitly, so it would always be the module
            for KA code.)  If you are moving a module, name_to_import should
            probably be the same as new_fullname (though it could technically
            be a prefix of new_fullname).
        import_alias: what to call the import.  Logically, we will suggest
            adding "import name_to_import as import_alias" though we may
            use "from" syntax if it amounts to the same thing.  If None,
            we'll just use "import name_to_import".
    """
    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        # First, set things up, and do some checks.
        assert _dotted_starts_with(new_fullname, name_to_import), (
            "%s isn't a valid name to import -- not a prefix of %s" % (
                name_to_import, new_fullname))

        old_localnames = list(  # so we can re-use it
            _localnames_from_fullnames(file_info, {old_fullname}))
        old_localname_strings = {ln.localname for ln in old_localnames}

        new_localname, need_new_import = _choose_best_localname(
            file_info, new_fullname, name_to_import, import_alias)

        # Now, patch references -- _replace_in_file does all the work.
        patches, used_localnames = _replace_in_file(
            file_info, old_fullname, old_localname_strings,
            new_fullname, new_localname)
        for patch in patches:
            yield patch

        # Finally, add a new import, if necessary.
        if need_new_import and used_localnames:
            # Decide what the import will say.
            import_stmt = _new_import_stmt(name_to_import, import_alias)

            old_imports = {ln.imp for ln in old_localnames
                           if ln.imp is not None}

            # Decide where to add it.  The issue here is that we may
            # be replacing a "late import" (an import inside a
            # function) in which case we want the new import to be
            # inside the same function at the same place.  In fact, we
            # might be late-importing the same module in *several*
            # functions, and each one has to get replaced properly.
            explicit_imports = {
                imp for imp in old_imports
                # TODO(benkraft): This is too weak -- we should only
                # call an import explicit if it is of the symbol's module
                # (see special case (2) in module docstring).
                if _dotted_starts_with(old_fullname, imp.name)}

            if not explicit_imports:
                # We need to add a totally new toplevel import, not
                # corresponding to an existing one.  (So we also don't
                # need to worry about copying comments or indenting.)
                yield _add_contextless_import_patch(
                    file_info, ['%s\n' % import_stmt])
            else:
                # There were existing imports of the old name,
                # so we try to match those.
                # TODO(benkraft): This doesn't work correctly in the case
                # where there was an implicit toplevel import, and an
                # explicit late import, and the moved symbol was used
                # outside the scope of the late import.  To handle this
                # case, we'll need to do much more careful tracing of which
                # imports exist in which scopes.
                for imp in explicit_imports:
                    # Copy the old import's context, such as opening indent
                    # and trailing newline.
                    # TODO(benkraft): If the context we copy is a comment, and
                    # we are keeping the old import, maybe don't copy it?
                    # TODO(benkraft): Should we look at preceding comments?
                    # We end up fighting with fix_python_imports if we do.
                    start, end = util.get_area_for_ast_node(
                        imp.node, file_info, include_previous_comments=False)
                    pre_context = body[start:imp.start]
                    post_context = body[imp.end:end]
                    # Now we can add the new import and have the same context
                    # as the import we are taking the place of!
                    text_to_add = ''.join(
                        [pre_context, import_stmt, post_context])
                    yield khodemod.Patch(filename, '', text_to_add,
                                         start, start)

    return suggestor


def _remove_imports_suggestor(old_fullname):
    """The suggestor to remove imports for now-changed references.

    Note that this should run after _fix_uses_suggestor.

    Arguments:
        old_fullname: the pre-move fullname (module when moving a module,
            module.symbol when moving a symbol) that we're moving.  (We
            only remove imports that could have gotten us that symbol.)
    """
    def suggestor(filename, body):
        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        # First, set things up, and do some checks.
        # TODO(benkraft): Don't recompute these; _fix_uses_suggestor has
        # already done so.
        old_localnames = _localnames_from_fullnames(file_info, {old_fullname})
        old_imports = {ln.imp for ln in old_localnames if ln.imp is not None}

        # Next, remove imports, if any are now unused.
        unused_imports, implicitly_used_imports = _unused_imports(
            old_imports, file_info)

        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor


def _fix_moved_region_suggestor(project_root, old_fullname, new_fullname):
    """Suggestor to fix up all the references to symbols in the moved region.

    When we move the definition of a symbol, it may reference other things in
    the source and/or destination modules as well as itself.  We need to fix up
    those references.  This works a lot like _fix_uses_suggestor, but we're
    actually sort of doing the reverse, since it's our code that's moving while
    the things we refer to stay where they are.  Like _fix_uses_suggestor, we
    additionally add necessary imports to the new file, although we leave it to
    _remove_moved_region_imports_suggestor to remove now-unused imports from
    the old file.

    Note that this should run after move_symbol_suggestor; it operates on the
    definition in its new location.  It only makes sense for symbols; when
    moving modules we don't encounter this issue.

    Arguments:
        project_root: as elsewhere
        old_fullname, new_module: the fullname of the symbol we are
            moving, before and after the move.
    """
    old_module, old_symbol = old_fullname.rsplit('.', 1)
    new_module, new_symbol = new_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the new file; that's where the moved
        # region will be by now.  (But we do look at both old and new.)
        # Caller should ensure this but we check to be safe.
        if util.module_name_for_filename(filename) != new_module:
            return

        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)
        try:
            old_filename = util.filename_for_module_name(old_module)
            old_file_info = util.File(
                old_filename,
                khodemod.read_file(project_root, old_filename) or '')
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        # Find the region we moved.
        toplevel_names_in_new_file = util.toplevel_names(file_info)
        if new_symbol not in toplevel_names_in_new_file:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in "
                                      "'%s': maybe it's defined weirdly?"
                                      % (new_symbol, new_module))
        node_to_fix = toplevel_names_in_new_file[new_symbol]

        # The moved region is full of localnames that make sense in the context
        # of old_file, but not new_file (since a localname depends on the
        # imports of the file, plus on whether it is a reference to something
        # in the current file).  For instance, if the code reegion had the text
        # `return oldfile_func() + newfile.newfile_func()` we want to rewrite
        # that to say `return oldfile.oldfile_func() + newfile_func()`, as well
        # as adding `import oldfile` to newfile.

        # Here, we make a LocalName object for each such localname, which will
        # help us rewrite them and add imports later.
        names_in_moved_code = {name for name, node in _all_names(node_to_fix)}
        # To construct the LocalNames, we typically need to associate an import
        # with them.  These imports live in the old file, if they're toplevel,
        # because that's where this code snippet used to live, or in the moved
        # region itself, if they're late.
        old_imports = itertools.chain(
            _compute_all_imports(old_file_info, toplevel_only=True),
            _compute_all_imports(file_info, within_node=node_to_fix))
        # Now construct the localnames.  The only special case is the moved
        # symbol itself, because it's already been moved to the new file, so
        # when we look at the old file we won't find it.
        localnames_in_old_file = list(_localnames_from_localnames(
            old_file_info, names_in_moved_code, old_imports))
        localnames_in_old_file.append(
            LocalName(old_fullname, old_symbol, None))
        # We construct a dict where, for each localname we've found above, we
        # map from the new fullname associated with the localname to the
        # LocalName object (containing the old fullname and its localname in
        # the old file).  (Note that for every symbol except the moved symbol,
        # those two fullnames are the same.)  Usually there will be only one
        # such localname for each fullname, but in case there are multiple (for
        # reasons described in the docstring of _localnames_from_fullnames), we
        # actually store a set of such LocalName objects.
        names_to_fix = {}
        for localname in localnames_in_old_file:
            if localname.fullname == old_fullname:
                # This is the moved symbol; we found it under its old fullname
                # but we want to track it under its new fullname.
                names_to_fix.setdefault(new_fullname, set()).add(localname)
            else:
                names_to_fix.setdefault(localname.fullname, set()).add(
                    localname)

        # Now, we fix up each name in turn.  This is the part that follows
        # _fix_uses_suggestor fairly closely.
        imports_to_add = set()
        for new_fullname_to_fix, old_localnames_to_fix in (
                names_to_fix.iteritems()):
            old_localname_strings = {
                ln.localname for ln in old_localnames_to_fix}
            # Find the old fullname (which should be the fullname in each item
            # of old_localnames_to_fix) and choose an import that we got it
            # from -- we choose the one with the shortest alias to minimize
            # line-wrapping.
            old_fullname_to_fix, _, imp = min(
                old_localnames_to_fix,
                key=lambda ln: -1 if ln.imp is None else len(ln.imp.alias))

            # Figure out by what name we'll refer to new_fullname_to_fix in the
            # new file.  _choose_best_localname does most of the work, but we
            # have to figure out what module we want to tell
            # _choose_best_localname to import if necessary.
            if imp and _dotted_starts_with(new_fullname_to_fix, imp.name):
                # If we got new_fullname_to_fix from an explicit import in the
                # old file, we'll do whatever that import did.
                name_to_import = imp.name
                import_alias = imp.alias
            elif imp:
                # If we got new_fullname_to_fix from an implicit import in the
                # old file, we'll still do whatever that import did.
                # TODO(benkraft): If we had an implicit import, we should
                # probably make it explicit rather than just copying.
                name_to_import = imp.name
                import_alias = None
            else:
                # If there was no corresponding import, we know this was a
                # symbol in the old file, so we tell _choose_best_localname to
                # import the module (where it now lives -- which is different
                # for the moved symbol itself), with no alias.
                # TODO(benkraft): Allow specifying an alias for the old module
                # in the new file.
                name_to_import, _ = new_fullname_to_fix.rsplit('.', 1)
                import_alias = None

            new_localname, need_new_import = _choose_best_localname(
                file_info, new_fullname_to_fix, name_to_import,
                import_alias)

            # Now, patch references.
            patches, used_localnames = _replace_in_file(
                file_info, old_fullname_to_fix, old_localname_strings,
                new_fullname_to_fix, new_localname, node_to_fix)
            for patch in patches:
                yield patch

            # We also *add* imports in this suggestor, because otherwise it's
            # too hard to tell what imports we need to add by the time we get
            # to _remove_moved_region_imports_suggestor.  Luckily, that doesn't
            # complicate things much here.
            if used_localnames and need_new_import:
                if imp:
                    start, end = util.get_area_for_ast_node(
                        imp.node, old_file_info,
                        include_previous_comments=False)
                    import_stmt = old_file_info.body[start:end]
                else:
                    import_stmt = '%s\n' % _new_import_stmt(name_to_import,
                                                            alias=None)
                imports_to_add.add(import_stmt)

        if imports_to_add:
            yield _add_contextless_import_patch(file_info, imports_to_add)

    return suggestor


def _remove_old_file_imports_suggestor(project_root, old_fullname):
    """Suggestor to remove unused imports from old-file after moving a region.

    When we move the definition of a symbol, it may have been the only user of
    some imports in its file.  We need to remove those now-unused imports.
    This runs after _fix_moved_region_suggestor, which probably added some of
    the imports we will remove to the new location of the symbol.

    Arguments:
        project_root: as elsewhere
        old_fullname: the pre-move fullname of the symbol we are moving
    """
    # TODO(benkraft): Instead of having three suggestors for removing imports
    # that do slightly different things, have options for a single suggestor.
    old_module, old_symbol = old_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the old file.  Caller should ensure this
        # but we check to be safe.
        if util.module_name_for_filename(filename) != old_module:
            return

        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        # Remove toplevel imports in the old file that are no longer used.
        # Sadly, it's difficult to determine which ones might be at all related
        # to the moved code, so we just remove anything that looks unused.
        # TODO(benkraft): Be more precise so we don't touch unrelated things.
        unused_imports, implicitly_used_imports = _unused_imports(
            _compute_all_imports(file_info, toplevel_only=True), file_info)
        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor


def _remove_moved_region_late_imports_suggestor(project_root, new_fullname):
    """Suggestor to remove unused imports after moving a region.

    When we move the definition of a symbol, it may have imported its new
    module as a "late-import"; this suggestor removes any such import.
    It runs after _fix_moved_region_suggestor and
    _remove_old_file_imports_suggestor, and only operates on the new file.
    TODO(benkraft): We should also remove late imports if the new file also
    imported the same module at the toplevel.

    Arguments:
        project_root: as elsewhere
        new_fullname: the post-move fullname of the symbol we are moving
    """
    new_module, new_symbol = new_fullname.rsplit('.', 1)

    def suggestor(filename, body):
        """filename is relative to the value of --root."""
        # We only need to operate on the new file; that's where the moved
        # region will be by now.  Caller should ensure this but we check to be
        # safe.
        if util.module_name_for_filename(filename) != new_module:
            return

        try:
            file_info = util.File(filename, body)
        except Exception as e:
            raise khodemod.FatalError(filename, 0,
                                      "Couldn't parse this file: %s" % e)

        # Find the region we moved.
        toplevel_names_in_new_file = util.toplevel_names(file_info)
        if new_symbol not in toplevel_names_in_new_file:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in "
                                      "'%s': maybe it's defined weirdly?"
                                      % (new_symbol, new_module))
        moved_node = toplevel_names_in_new_file[new_symbol]

        # Remove imports in the moved region itself that are no longer used.
        # This should probably just be imports of new_module, or things that
        # got us it, so we only look at those.
        unused_imports, implicitly_used_imports = _unused_imports(
            {imp for imp in _compute_all_imports(
                file_info, within_node=moved_node)
             if _import_provides_module(imp, new_module)},
            file_info, within_node=moved_node)
        for imp in implicitly_used_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in unused_imports:
            yield _remove_import_patch(imp, file_info)

    return suggestor


def _remove_empty_files_suggestor(filename, body):
    """Suggestor to remove any empty files we leave behind.

    We also remove the file if it has only __future__ imports.  If all that's
    left is docstrings, comments, and non-__future__ imports, we warn but don't
    remove it.  (We ignore __init__.py files since those are often
    intentionally empty or kept only for some imports.)
    """
    if os.path.basename(filename) == '__init__.py':
        # Ignore __init__.py files.
        return

    try:
        file_info = util.File(filename, body)
    except Exception as e:
        raise khodemod.FatalError(filename, 0,
                                  "Couldn't parse this file: %s" % e)

    has_docstrings_comments_or_imports = '#' in body
    for stmt in file_info.tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Str):
            # A docstring.
            has_docstrings_comments_or_imports = True
        elif isinstance(stmt, ast.ImportFrom) and stmt.module == '__future__':
            # A __future__ import, which won't force us to keep the file.
            pass
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            # A non-__future__ import.
            has_docstrings_comments_or_imports = True
        else:
            # Some real code; we don't want to do anything.
            return

    # If we've gotten here, there's no "real code".
    if has_docstrings_comments_or_imports:
        yield khodemod.WarningInfo(
            filename, 0, "This file looks mostly empty; consider removing it.")
    else:
        # It's actually empty, so we can just go ahead and remove.
        yield khodemod.Patch(filename, body, None, 0, len(body))


def _remove_leading_whitespace_suggestor(filename, body):
    """Suggestor to remove any leading whitespace we leave behind."""
    lstripped_body = body.lstrip()
    if lstripped_body != body:
        whitespace_len = len(body) - len(lstripped_body)
        yield khodemod.Patch(filename, body[:whitespace_len], '',
                             0, whitespace_len)


def _import_sort_suggestor(project_root):
    """Suggestor to fix up imports in a file."""
    fix_imports_flags = FakeOptions(project_root)

    def suggestor(filename, body):
        """`filename` relative to project_root."""
        # TODO(benkraft): merge this with the import-adding, so we just show
        # one diff to add in the right place, unless there is additional
        # sorting to do.
        # Now call out to fix_python_imports to do the import-sorting
        change_record = fix_python_imports.ChangeRecord('fake_file.py')

        # A modified version of fix_python_imports.GetFixedFile
        # NOTE: fix_python_imports needs the rootdir to be on the
        # path so it can figure out third-party deps correctly.
        # (That's in addition to having it be in FakeOptions, sigh.)
        try:
            sys.path.insert(0, os.path.abspath(project_root))
            file_line_infos = fix_python_imports.ParseOneFile(
                body, change_record)
            fixed_lines = fix_python_imports.FixFileLines(
                change_record, file_line_infos, fix_imports_flags)
        finally:
            del sys.path[0]

        if fixed_lines is None:
            return
        fixed_body = ''.join(['%s\n' % line for line in fixed_lines
                              if line is not None])
        if fixed_body == body:
            return

        diffs = difflib.SequenceMatcher(None, body, fixed_body).get_opcodes()
        for op, i1, i2, j1, j2 in diffs:
            if op != 'equal':
                yield khodemod.Patch(filename,
                                     body[i1:i2], fixed_body[j1:j2], i1, i2)

    return suggestor


def make_fixes(old_fullnames, new_fullname, import_alias=None,
               project_root='.', automove=True, verbose=False):
    """Do all the fixing necessary to move old_fullnames to new_fullname.

    Arguments: parallel to the commandline -- see there for details.

    We proceed as follows.  Each step runs one or more khodemod suggestors to
    make its changes.
    1) Figure out what the inputs mean, in terms of what modules/symbols need
       to go where (inputs.expand_and_normalize).
    2) For each moved module or symbol:
       2a) If automove is set, and we're moving a module, simply move it to its
           new filename (moves.move_module_suggestor).
       2b) If automove is set, and we're moving a symbol, first move the
           definition-region (moves.move_symbol_suggestor), then update
           it and the imports of the source and destination files to match
           (_fix_moved_region_suggestor and
           _remove_moved_region_imports_suggestor).
    3) Fix references in all other files, including updating their imports
       (_fix_uses_suggestor and _remove_imports_suggestor).
    4) Clean up: remove the module(s) we moved things out of, if it is now
       empty (_remove_empty_files_suggestor), and resort imports in any file we
       touched (_import_sort_suggestor).
    """
    def log(msg):
        if verbose:
            print msg

    # TODO(benkraft): Support other khodemod frontends.
    frontend = khodemod.AcceptingFrontend(verbose=verbose)

    # Return a list of (old_fullname, new_fullname) pairs that we can rename.
    old_new_fullname_pairs = inputs.expand_and_normalize(
        project_root, old_fullnames, new_fullname)

    for (oldname, newname, is_symbol) in old_new_fullname_pairs:
        if automove:
            log("===== Moving %s to %s =====" % (oldname, newname))
            if is_symbol:
                old_filename = util.filename_for_module_name(
                    oldname.rsplit('.', 1)[0])
                move_suggestor = moves.move_symbol_suggestor(
                    project_root, oldname, newname)
            else:
                old_filename = util.filename_for_module_name(oldname)
                move_suggestor = moves.move_module_suggestor(
                    project_root, oldname, newname)
            frontend.run_suggestor_on_files(move_suggestor, [old_filename],
                                            root=project_root)
            if is_symbol:
                new_filename = util.filename_for_module_name(
                    newname.rsplit('.', 1)[0])
                fix_moved_region_suggestor = _fix_moved_region_suggestor(
                    project_root, oldname, newname)
                frontend.run_suggestor_on_files(
                    fix_moved_region_suggestor, [new_filename],
                    root=project_root)

                remove_old_file_imports_suggestor = (
                    _remove_old_file_imports_suggestor(project_root, oldname))
                frontend.run_suggestor_on_files(
                    remove_old_file_imports_suggestor, [old_filename],
                    root=project_root)

                remove_moved_region_late_imports_suggestor = (
                    _remove_moved_region_late_imports_suggestor(
                        project_root, newname))
                frontend.run_suggestor_on_files(
                    remove_moved_region_late_imports_suggestor, [new_filename],
                    root=project_root)

        log("===== Updating references of %s to %s =====" % (oldname, newname))
        if is_symbol:
            name_to_import = newname.rsplit('.', 1)[0]
        else:
            name_to_import = newname

        fix_uses_suggestor = _fix_uses_suggestor(
            oldname, newname, name_to_import, import_alias)
        frontend.run_suggestor(fix_uses_suggestor, root=project_root)

        remove_imports_suggestor = _remove_imports_suggestor(oldname)
        frontend.run_suggestor_on_modified_files(remove_imports_suggestor)

    log("===== Cleaning up empty files & whitespace =====")
    frontend.run_suggestor_on_modified_files(_remove_empty_files_suggestor)
    frontend.run_suggestor_on_modified_files(
        _remove_leading_whitespace_suggestor)

    log("===== Resorting imports =====")
    import_sort_suggestor = _import_sort_suggestor(project_root)
    frontend.run_suggestor_on_modified_files(import_sort_suggestor)

    log("===== Move complete! =====")


def main():
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    # TODO(csilvers): allow moving multiple files into a single directory too.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_fullnames', metavar='old_fullname', nargs='+',
                        help=('fullname to move: can be path.to.package, '
                              'path.to.package.module, '
                              'path.to.package.module.symbol, '
                              'some/dir, or some/dir/file.py'))
    parser.add_argument('new_fullname',
                        help=('fullname to rename to. This can always be of '
                              'the same "type" as old_fullname, but can '
                              'also be one level up: e.g. moving a symbol '
                              'to a module, or a module to a package. It '
                              '*must* be one level up if multiple '
                              'old_fullnames are specified.'))
    parser.add_argument('--no-automove', dest='automove',
                        action='store_false', default=True,
                        help=('Do not automatically move OLD_FULLNAME to '
                              'NEW_FULLNAME. Callers must do that before '
                              'running this script.'))
    parser.add_argument('-a', '--alias',
                        help=('Alias to use when adding new import lines.  '
                              'This is the module-alias, even if you are '
                              'moving a symbol.'))
    parser.add_argument('--root', default='.',
                        help=('The project-root of the directory-tree you '
                              'want to do the renaming in.  old_fullname, '
                              'and new_fullname are taken relative to root.'))
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Print some information about what we're doing.")
    parsed_args = parser.parse_args()

    make_fixes(
        parsed_args.old_fullnames, parsed_args.new_fullname,
        import_alias=parsed_args.alias,
        project_root=parsed_args.root,
        automove=parsed_args.automove,
        verbose=parsed_args.verbose)


if __name__ == '__main__':
    main()
