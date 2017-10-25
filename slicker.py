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

High level terminology:
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
LocalName = collections.namedtuple(
    'LocalName', ['fullname', 'localname', 'imp'])


def _compute_all_imports(file_info, within_node=None, toplevel_only=False):
    """Return info about the imports in this file.

    If node is passed, only return imports within that node.  If toplevel_only
    is truthy, look only at imports at the toplevel of the module -- not inside
    if, functions, etc.  (We don't support setting both at once.)  Otherwise,
    look at the whole file.

    Returns a set of Import objects.
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
                else:
                    imports.add(
                        Import('%s.%s' % (node.module, alias.name),
                               alias.asname or alias.name, start, end, node))
    return imports


def _determine_localnames(fullname, file_info,
                          within_node=None, toplevel_only=False):
    """Return info about the localnames by which `fullname` goes in this file.

    within_node and toplevel_only are passed through to _compute_all_imports.

    Returns a set of LocalName namedtuples.

    It might seem like this set should always have size 1, but there
    are several cases it might have more:
    1) If you do 'import foo.bar' and 'import foo.baz', then
       'foo.bar.myfunc' is actually provided through *both*
       imports (a quirk of python), leading to two elements
       in the set.  We only care about the first element,
       of course.
    2) If you do 'import foo.bar' and 'from foo import bar',
       then 'foo.bar.myfunc' is provided through both imports.
       I hope you don't do that.
    3) If you do '   import foo.bar' several times in several
       functions (several "late imports") you'll get one
       return-value per late-import that you do.
    """
    localnames = set()
    for imp in _compute_all_imports(file_info, within_node=within_node,
                                    toplevel_only=toplevel_only):
        if imp.alias == imp.name:      # no aliases: no 'as' or 'from'
            # This deals with the python quirk in case (1) of the
            # docstring: 'import foo.anything' gives you access
            # to foo.bar.myfunc.
            imported_firstpart = imp.name.split('.', 1)[0]
            fullname_firstpart = fullname.split('.', 1)[0]
            if imported_firstpart == fullname_firstpart:
                localnames.add(LocalName(fullname, fullname, imp))
        else:                          # alias: need to replace name with alias
            if _dotted_starts_with(fullname, imp.name):
                localname = '%s%s' % (imp.alias, fullname[len(imp.name):])
                localnames.add(LocalName(fullname, localname, imp))

    # If the name is a specific symbol defined in the file on which we are
    # operating, we also treat the unqualified reference as a localname, with
    # null import.
    current_module_name = util.module_name_for_filename(file_info.filename)
    if (_dotted_starts_with(fullname, current_module_name)
            and fullname != current_module_name):
        # Note that in this case localnames is likely empty if we get here,
        # although it's not guaranteed since python lets you do `import
        # foo.bar` in foo/bar.py, at least in some cases.
        unqualified_name = fullname[len(current_module_name) + 1:]
        localnames.add(LocalName(fullname, unqualified_name, None))

    return localnames


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
    That's not going to work!  Similarly if our file has
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


def _imports_to_remove(localnames_for_old_fullname, new_localname,
                       used_localnames, file_info):
    """Decide what imports we can remove.

    Arguments:
        localnames_for_old_fullname: set of LocalNames that reflect
           how old_fullname -- the pre-move fullname of the symbol
           that we're moving -- is potentially referred to in the
           given file.  (Usually this set will have size 1, but see
           docstring for _determine_localnames().)
        new_localname: the post-move localname of the symbol that we're
           moving.
        used_localnames: the set of localnames that *actually* occurred
           in this file.  This is a subset of localnames_for_old_fullname,
           which holds those localnames which could legally occur in
           the file but may not.  (More precisely, it's a subset of
           {ln.localname for ln in localnames_for_old_fullname}.)
        file_info: the util.File object.

    Returns (set of imports we can remove,
             set of imports that may be used implicitly).

    "set of imports that may be used implicitly" is when we do
    "import foo.bar" and access "foo.baz.myfunc()", which is legal
    but weird python.
    """
    # Decide whether to keep the old import if we changed references to it.
    removable_imports = set()
    maybe_removable_imports = set()
    definitely_kept_imports = set()
    for (fullname, localname, imp) in localnames_for_old_fullname:
        if imp is None:
            # If this localname didn't correspond to an import, ignore it.
            continue
        if new_localname == localname:
            # This can happen if we're moving foo.myfunc to bar.myfunc
            # and this file does 'import foo as bar; bar.myfunc()'.
            # In that case the localname is unchanged (it's bar.myfunc
            # both before and after the move) and all we need to do is
            # change the import line by removing the old import and
            # adding the new one.  (We only do the removing here.)
            removable_imports.add(imp)
        elif localname in used_localnames:
            # This means that this localname is actually used in our
            # file.  We need to check if there are any other names in
            # this file that depend on `imp`.  e.g. we are moving
            # foo.myfunc to bar.myfunc, and our current file has
            # 'x = foo.myfunc()'.  Our question is, does it also have
            # code like 'y = foo.myotherfunc()'?  If so, we can't
            # remove the 'import foo' since it has this other client.
            # Otherwise we can since *all* uses of foo are changing to
            # be uses of bar.

            # This includes all names that we might be *implicitly*
            # accessing via this import, due to the python quirk
            # around 'import foo.bar; foo.baz.myfunc()' working.
            relevant_names = set(_names_starting_with(
                imp.alias.split('.', 1)[0], file_info.tree))
            # This is only those names that we are explicitly accessing
            # via this import, i.e. not depending on the quirk.
            explicit_names = {
                name for name in relevant_names
                if _dotted_starts_with(name, imp.alias)}
            handled_names = {
                name for name in relevant_names
                if _dotted_starts_with(name, localname)}

            if explicit_names - handled_names:
                # If we make use of this import, other than for the
                # moved symbol, we need to keep it.
                definitely_kept_imports.add(imp)
            elif relevant_names - handled_names:
                # If we make use of this import but only implicitly
                # (via the quirk), we may be able to remove it or we
                # may not, depending on whether anyone else implicitly
                # (or explicitly) provides the same symbol.
                maybe_removable_imports.add(imp)
            else:
                removable_imports.add(imp)
        else:
            definitely_kept_imports.add(imp)

    # Now, if there was an import we were considering removing, and we are
    # keeping a different import that gets us the same things, we can
    # definitely remove the former.
    for maybe_removable_imp in list(maybe_removable_imports):
        for kept_imp in definitely_kept_imports:
            if (maybe_removable_imp.alias.split('.')[0] ==
                    kept_imp.alias.split('.')[0]):
                maybe_removable_imports.remove(maybe_removable_imp)
                removable_imports.add(maybe_removable_imp)
                break

    return (removable_imports, maybe_removable_imports)


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
            start, end = file_info.tokens.get_text_range(node)
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
    joined_imports = ''.join('%s\n' % text for text in import_texts)
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


# TODO(benkraft): Once slicker can do it relatively easily, move the
# use-fixing suggestors and helpers to their own file.
def _fix_uses_suggestor(old_fullname, new_fullname,
                        name_to_import, import_alias=None):
    """The main suggestor to fix all references to a file.

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

        # PART THE FIRST:
        #    Set things up, do some simple checks, decide whether to operate.

        assert _dotted_starts_with(new_fullname, name_to_import), (
            "%s isn't a valid name to import -- not a prefix of %s" % (
                name_to_import, new_fullname))

        old_localnames = _determine_localnames(old_fullname, file_info)
        old_localname_strings = {ln.localname for ln in old_localnames}

        # If name_to_import is already imported in this file,
        # figure out what the localname for our symbol would
        # be using this existing import.  That is, if we are moving
        # 'foo.myfunc' to 'bar.myfunc' and this file already has
        # 'import bar as baz' then existing_new_localnames would be
        # {'baz.myfunc'}.
        existing_new_localnames = {
            ln.localname
            for ln in _determine_localnames(new_fullname, file_info)
            if ln.imp is None or name_to_import == ln.imp.name
        }

        if existing_new_localnames:
            # If for some reason there are multiple existing localnames
            # (unlikely), choose the shortest one, to save us line-wrapping.
            # Prefer an existing explicit import to the caller-provided alias.
            # TODO(benkraft): this might not be totally safe if the existing
            # import isn't toplevel, but probably it will be.
            new_localname = min(existing_new_localnames, key=len)
        elif import_alias:
            new_localname = import_alias + new_fullname[len(name_to_import):]
        else:
            new_localname = new_fullname

        if not existing_new_localnames:
            conflicting_imports = _check_import_conflicts(
                file_info, import_alias or name_to_import, bool(import_alias))
            if conflicting_imports:
                raise khodemod.FatalError(
                    filename, conflicting_imports.pop().start,
                    "Your alias will conflict with imports in this file.")

        # PART THE SECOND:
        #    Patch references to the symbol inline -- everything but imports.
        patches, used_localnames = _replace_in_file(
            file_info, old_fullname, old_localname_strings,
            new_fullname, new_localname)
        for patch in patches:
            yield patch

        # PART THE THIRD:
        #    Add/remove imports, if necessary.

        # We didn't change anything that would require fixing imports.
        if not used_localnames:
            return

        removable_imports, maybe_removable_imports = _imports_to_remove(
            old_localnames, new_localname, used_localnames, file_info)

        for imp in maybe_removable_imports:
            yield khodemod.WarningInfo(
                filename, imp.start, "This import may be used implicitly.")
        for imp in removable_imports:
            toks = list(
                file_info.tokens.get_tokens(imp.node, include_extra=False))
            next_tok = file_info.tokens.next_token(
                toks[-1], include_extra=True)
            if next_tok.type == tokenize.COMMENT and (
                    '@nolint' in next_tok.string.lower() or
                    '@unusedimport' in next_tok.string.lower()):
                # Don't touch nolinted imports; they may be there for a reason.
                # TODO(benkraft): Handle this case for implicit imports as well
                yield khodemod.WarningInfo(
                    filename, imp.start, "Not removing import with @Nolint.")
            elif ',' in body[imp.start:imp.end]:
                # TODO(benkraft): better would be to check for `,` in each
                # token so we don't match commas in internal comments.
                yield khodemod.WarningInfo(
                    filename, imp.start,
                    "I don't know how to edit this import.")
            else:
                # TODO(benkraft): Should we look at preceding comments?
                # We end up fighting with fix_python_imports if we do.
                start, end = util.get_area_for_ast_node(
                    imp.node, file_info, include_previous_comments=False)
                yield khodemod.Patch(filename, body[start:end], '', start, end)

        # Add a new import, if necessary.
        if not existing_new_localnames:
            # Decide what the import will say.
            # TODO(csilvers): properly handle the case that
            # name_to_import is "module.symbol" and import_alias is not None.
            if '.' in name_to_import and import_alias:
                base, suffix = name_to_import.rsplit('.', 1)
                if import_alias == suffix:
                    import_stmt = 'from %s import %s' % (base, suffix)
                else:
                    import_stmt = 'import %s as %s' % (
                        name_to_import, import_alias)
            else:
                if import_alias and import_alias != name_to_import:
                    import_stmt = 'import %s as %s' % (
                        name_to_import, import_alias)
                else:
                    import_stmt = 'import %s' % name_to_import

            old_imports = {
                ln.imp for ln in old_localnames if ln.imp is not None}
            # Decide where to add it.  The issue here is that we may
            # be replacing a "late import" (an import inside a
            # function) in which case we want the new import to be
            # inside the same function at the same place.  In fact, we
            # might be late-importing the same module in *several*
            # functions, and each one has to get replaced properly.
            explicit_imports = {
                imp for imp in old_imports
                # TODO(benkraft): This is too weak -- we should only
                # call an import explicit if it is of the symbol's module.
                if _dotted_starts_with(old_fullname, imp.name)}

            if not explicit_imports:
                # We need to add a totally new toplevel import, not
                # corresponding to an existing one.  (So we also don't
                # need to worry about copying comments or indenting.)
                yield _add_contextless_import_patch(file_info, [import_stmt])
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


def _fix_moved_region_suggestor(project_root, old_fullname, new_fullname):
    """Suggestor to fix up all the references to symbols in the moved region.

    When we move the definition of a symbol, it may reference other things in
    the source and/or destination modules as well as itself.  We need to fix up
    those references.  This works a lot like _fix_uses_suggestor, but we're
    actually sort of doing the reverse, since it's our code that's moving while
    the things we refer to stay where they are.

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

        # PART THE ZEROTH:
        #    Do global setup, common to all names to fix up.

        # Figure out what names there are to consider.
        new_file_names = util.toplevel_names(file_info)
        old_file_names = util.toplevel_names(old_file_info)

        if new_symbol not in new_file_names:
            raise khodemod.FatalError(filename, 0,
                                      "Could not find symbol '%s' in "
                                      "'%s': maybe it's defined weirdly?"
                                      % (new_symbol, new_module))
        node_to_fix = new_file_names[new_symbol]

        # Compute the pairs (old_fullname, new_fullname) we want to fix.  For
        # most of these symbols, the two fullnames will be the same, but we
        # also need to fix up references to the moved symbol itself.
        names_to_fix = set()
        for name in old_file_names:
            fullname = '%s.%s' % (old_module, name)
            names_to_fix.add((fullname, fullname))
        for name in new_file_names:
            new_fullname = '%s.%s' % (new_module, name)
            if name == new_symbol:
                old_fullname = '%s.%s' % (old_module, old_symbol)
            else:
                old_fullname = new_fullname
            names_to_fix.add((old_fullname, new_fullname))

        # Now, we fix up each name in turn.  This is the part that follows
        # _fix_uses_suggestor fairly closely.
        # TODO(benkraft): Share common parts with _fix_uses_suggestor.
        imports_to_add = set()
        for old_fullname_to_fix, new_fullname_to_fix in names_to_fix:
            # PART THE FIRST:
            #    Do setup specific to each name to fix up.
            name_to_import, _ = new_fullname_to_fix.rsplit('.', 1)

            old_localnames = (
                _determine_localnames(old_fullname_to_fix, old_file_info,
                                      toplevel_only=True) |
                _determine_localnames(old_fullname_to_fix, file_info,
                                      within_node=node_to_fix))
            old_localname_strings = {ln.localname for ln in old_localnames}

            # If name_to_import is already imported in this file, figure out
            # what the localname for new_fullname_to_fix would be using this
            # existing import.  That is, if we are fixing references to some
            # function 'foo.helper' called in the moved region, and bar.py
            # already has 'import foo as baz', then existing_new_localnames
            # would be {'baz.helper'}.
            existing_new_localnames = {
                ln.localname
                for ln in _determine_localnames(new_fullname_to_fix, file_info)
                if ln.imp is None or name_to_import == ln.imp.name
            }

            if existing_new_localnames:
                # If for some reason there are multiple existing localnames
                # (unlikely), choose the shortest one, to save us
                # line-wrapping.  Prefer an existing explicit import to the
                # caller-provided alias.
                # TODO(benkraft): this might not be totally safe if the
                # existing import isn't toplevel, but probably it will be.
                new_localname = min(existing_new_localnames, key=len)
            else:
                # TODO(benkraft): Allow specifying an alias for the old module
                # in the new file.
                new_localname = new_fullname_to_fix

            if not existing_new_localnames:
                # TODO(benkraft): Maybe do this check for every name before
                # fixing up any of them?  (And only do it once for each
                # distinct name_to_import.)
                conflicting_imports = _check_import_conflicts(
                    file_info, name_to_import, False)
                if conflicting_imports:
                    raise khodemod.FatalError(
                        filename, conflicting_imports.pop().start,
                        "Your alias will conflict with imports in this file.")

            # PART THE SECOND:
            #    Patch references to the symbol inline -- everything but
            #    imports.
            patches, used_localnames = _replace_in_file(
                file_info, old_fullname_to_fix, old_localname_strings,
                new_fullname_to_fix, new_localname, node_to_fix)
            for patch in patches:
                yield patch

            if used_localnames and not existing_new_localnames:
                imports_to_add.add(name_to_import)

        # PART THE THIRD:
        #    Add new imports, if necessary.
        if imports_to_add:
            yield _add_contextless_import_patch(
                file_info, ['import %s' % imp for imp in imports_to_add])

        # TODO(benkraft): Remove imports from the old file, if applicable.

    return suggestor


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


def make_fixes(old_fullname, new_fullname, import_alias=None,
               project_root='.', automove=True, verbose=False):
    """name_to_import is the module-part of new_fullname."""
    def log(msg):
        if verbose:
            print msg

    # TODO(benkraft): Support other khodemod frontends.
    frontend = khodemod.AcceptingFrontend(verbose=verbose)

    # Return a list of (old_fullname, new_fullname) pairs that we can rename.
    old_new_fullname_pairs = inputs.expand_and_normalize(
        project_root, old_fullname, new_fullname)

    for (oldname, newname, is_symbol) in old_new_fullname_pairs:
        if automove:
            # TODO(benkraft): Each of these really only wants to run on one
            # file, and knows which; specify that in a better way rather than
            # traversing them all.
            log("===== Moving %s to %s =====" % (oldname, newname))
            if is_symbol:
                move_suggestor = moves.move_symbol_suggestor(
                    project_root, oldname, newname)
            else:
                move_suggestor = moves.move_module_suggestor(
                    project_root, oldname, newname)
            frontend.run_suggestor(move_suggestor, root=project_root)
            if is_symbol:
                fix_moved_region_suggestor = _fix_moved_region_suggestor(
                    project_root, oldname, newname)
                frontend.run_suggestor(
                    fix_moved_region_suggestor, root=project_root)

        log("===== Updating references of %s to %s =====" % (oldname, newname))
        if is_symbol:
            name_to_import = newname.rsplit('.', 1)[0]
        else:
            name_to_import = newname

        fix_uses_suggestor = _fix_uses_suggestor(
            oldname, newname, name_to_import, import_alias)
        frontend.run_suggestor(fix_uses_suggestor, root=project_root)

    log("====== Resorting imports ======")
    import_sort_suggestor = _import_sort_suggestor(project_root)
    frontend.run_suggestor_on_modified_files(import_sort_suggestor)

    log("======== Move complete! =======")


def main():
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    # TODO(csilvers): allow moving multiple files into a single directory too.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_fullname')
    parser.add_argument('new_fullname')
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
        parsed_args.old_fullname, parsed_args.new_fullname,
        import_alias=parsed_args.alias,
        project_root=parsed_args.root,
        automove=parsed_args.automove,
        verbose=parsed_args.verbose)


if __name__ == '__main__':
    main()
