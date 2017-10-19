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


import argparse
import ast
import collections
import difflib
import os
import re
import sys
import tokenize

import asttokens

import khodemod

# After importing everything else, but before importing fix_python_imports, we
# want to add cwd to the python path, so that fix_python_imports can find what
# modules are third-party correctly.
# TODO(benkraft): refactor fix_python_imports so this is easier.
sys.path.insert(0, os.getcwd())
import fix_python_imports


def _re_for_name(name):
    """Find a dotted-name (a.b.c) given that Python allows whitespace.

    Note we check for *top-level* dotted names, so we would not match
    'd.a.b.c.'
    """
    # TODO(csilvers): replace '\s*' by '\s*#\s*' below, and then we
    # can use this to match line-broken dotted-names inside comments too!
    return re.compile(r'(?<!\.)\b%s\b' %
                      re.escape(name).replace(r'\.', r'\s*\.\s*'))


def _filename_for_module_name(module_name):
    """filename is relative to a sys.path entry, such as your project-root."""
    return '%s.py' % module_name.replace('.', '/')


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
    safe_headers = True


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
#        it *is* the name! [except in weird cases])
# So in the above example, if we were searching for foo.bar.some_function
# in a file that had 'from foo import bar', we'd get a LocalName
# with name='foo.bar.some_function' and localname='bar.some_function'.
#  See test cases for more examples.
LocalName = collections.namedtuple(
    'LocalName', ['fullname', 'localname', 'imp'])


def _compute_all_imports(file_info):
    """Return info about the imports in this file.

    Returns a set of Import objects.
    """
    imports = set()
    for node in ast.walk(file_info.tree):
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


def _determine_localnames(fullname, file_info):
    """Return info about the localnames by which `fullname` goes in this file.

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
    imports = set()
    for imp in _compute_all_imports(file_info):
        if imp.alias == imp.name:      # no aliases: no 'as' or 'from'
            # This deals with the python quirk in case (1) of the
            # docstring: 'import foo.anything' gives you access
            # to foo.bar.myfunc.
            imported_firstpart = imp.name.split('.', 1)[0]
            fullname_firstpart = fullname.split('.', 1)[0]
            if imported_firstpart == fullname_firstpart:
                imports.add(LocalName(fullname, fullname, imp))
        else:                          # alias: need to replace name with alias
            if _dotted_starts_with(fullname, imp.name):
                localname = '%s%s' % (imp.alias, fullname[len(imp.name):])
                imports.add(LocalName(fullname, localname, imp))
    return imports


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


def _names_starting_with(prefix, file_info):
    """Returns all dotted names in the given file beginning with 'prefix'.

    Does not include imports or string references or anything else funky like
    that.  "Beginning with prefix" in the dotted sense (see
    _dotted_starts_with).

    Returns a dict of name -> list of AST nodes.
    """
    retval = {}
    for name, node in _all_names(file_info.tree):
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
    TODO(benkraft): Also check if there are variable-names that
    collide.
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
                       patched_localnames, file_info):
    """Decide what imports we can remove.

    Arguments:
        localnames_for_old_fullname: set of LocalNames that reflect
           how old_fullname -- the pre-move fullname of the symbol
           that we're moving -- is potentially referred to in the
           given file.  (Usually this set will have size 1, but see
           docstring for _determine_localnames().)
        new_localname: the post-move localname of the symbol that we're
           moving.
        patched_localnames: the set of localnames whose references we
           patched.  These are the localnames that *actually* occurred
           in this file.  This is a subset of localnames_for_old_fullname,
           which holds those localnames which could legally occur in
           the file but may not.  (More precisely, it's a subset of
           {ln.localname for ln in localnames_for_old_fullname}.)
        file_info: the File object.

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
        if new_localname == localname:
            # This can happen if we're moving foo.myfunc to bar.myfunc
            # and this file does 'import foo as bar; bar.myfunc()'.
            # In that case the localname is unchanged (it's bar.myfunc
            # both before and after the move) and all we need to do is
            # change the import line by removing the old import and
            # adding the new one.  (We only do the removing here.)
            removable_imports.add(imp)
        elif localname in patched_localnames:
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
                imp.alias.split('.', 1)[0], file_info))
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


def _get_import_area(imp, file_info):
    """Return the start/end character offsets of the whole import region.

    We include everything that is part of the same line, as well as its ending
    newline, (but excluding semicolons), as part of the import region.

    TODO(benkraft): Should we look at preceding full-line comments?  We end up
    fighting with fix_python_imports if we do.
    """
    toks = list(file_info.tokens.get_tokens(imp.node, include_extra=True))
    first_tok = toks[0]
    last_tok = toks[-1]

    # prev_tok will be the last token before the import area, or None if there
    # isn't one.
    prev_tok = next(reversed(
        [tok for tok in file_info.tokens.tokens[:first_tok.index]
         if tok.string == '\n' or not tok.string.isspace()]), None)

    for tok in file_info.tokens.tokens[last_tok.index + 1:]:
        if tok.type == tokenize.COMMENT:
            last_tok = tok
        elif tok.string == '\n':
            last_tok = tok
            break
        else:
            break

    return (prev_tok.endpos if prev_tok else 0, last_tok.endpos)


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


class File(object):
    """Represents information about a file.

    TODO(benkraft): Also cache things like _compute_all_imports.
    """
    def __init__(self, filename, body):
        """filename is relative to the value of --root."""
        self.filename = filename
        self.body = body
        self.tree = ast.parse(body)
        self.tokens = asttokens.ASTTokens(body, tree=self.tree)


def fix_uses_suggestor(old_fullname, new_fullname,
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
            file_info = File(filename, body)
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

        # If name_to_import is already imported in this file, figure
        # out what the localname for our symbol would be using this
        # existing import.  That is, if we are moving 'foo.myfunc' to
        # 'bar.myfunc' and this file already has 'import bar as baz'
        # then existing_new_localnames would be {'baz.myfunc'}.
        existing_new_localnames = {
            ln.localname
            for ln in _determine_localnames(new_fullname, file_info)
            if name_to_import == ln.imp.name
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

        # First, fix up normal references in code.
        patched_localnames = set()
        for localname in old_localname_strings - {new_localname}:
            for (name, ast_nodes) in (
                    _names_starting_with(localname, file_info).iteritems()):
                for node in ast_nodes:
                    start, end = file_info.tokens.get_text_range(node)
                    patched_localnames.add(localname)
                    yield khodemod.Patch(
                        filename,
                        body[start:end], new_localname + name[len(localname):],
                        start, end)

        # Fix up references in strings and comments.  We look for both the
        # fully-qualified name and any aliases in use in this file, as well as
        # the filename if we are moving a module.  We always replace
        # fully-qualified references with fully-qualified references;
        # references to aliases get replaced with whatever we're using for the
        # rest of the file.
        regexes_to_check = [(_re_for_name(old_fullname), new_fullname)]
        for localname in old_localname_strings - {new_localname, old_fullname}:
            regexes_to_check.append((_re_for_name(localname), new_localname))
        # Also check for the fullname being represented as a file.
        # In cases where the fullname is not a module (but is instead
        # module.symbol) this will typically be a noop.
        regexes_to_check.append((
            re.compile(re.escape(_filename_for_module_name(old_fullname))),
            _filename_for_module_name(new_fullname)))

        # Strings
        for node in ast.walk(file_info.tree):
            if isinstance(node, ast.Str):
                start, end = file_info.tokens.get_text_range(node)
                str_tokens = list(
                    file_info.tokens.get_tokens(node, include_extra=True))
                for regex, replacement in regexes_to_check:
                    if regex.search(node.s):
                        for patch in _replace_in_string(
                                str_tokens, regex, replacement, file_info):
                            yield patch

        # Comments
        for token in file_info.tokens.tokens:
            if token.type == tokenize.COMMENT:
                for regex, replacement in regexes_to_check:
                    # TODO(benkraft): Handle names broken across multiple lines
                    # of comments.
                    for match in regex.finditer(token.string):
                        yield khodemod.Patch(
                            filename,
                            match.group(0), replacement,
                            token.startpos + match.start(),
                            token.startpos + match.end())

        # PART THE THIRD:
        #    Add/remove imports, if necessary.

        if (not patched_localnames and
                # This protects against the case where the use didn't change
                # but the import needs to, e.g. when moving foo.myfunc to
                # bar.myfunc and our file used to have 'import foo as bar'.
                # TODO(benkraft): I think we do extra work here if we don't
                # change the alias but also don't have any references.
                new_localname not in old_localname_strings):
            # We didn't change anything that would require fixing imports.
            return

        removable_imports, maybe_removable_imports = _imports_to_remove(
            old_localnames, new_localname, patched_localnames, file_info)

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
                start, end = _get_import_area(imp, file_info)
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

            # Decide where to add it.  The issue here is that we may
            # be replacing a "late import" (an import inside a
            # function) in which case we want the new import to be
            # inside the same function at the same place.  In fact, we
            # might be late-importing the same module in *several*
            # functions, and each one has to get replaced properly.
            explicit_imports = {
                ln.imp for ln in old_localnames
                # TODO(benkraft): This is too weak -- we should only
                # call an import explicit if it is of the symbol's module.
                if _dotted_starts_with(old_fullname, ln.imp.name)}

            if explicit_imports:
                # If there previously existed an explicit import, we add at the
                # location of each explicit import, and only those.
                # TODO(benkraft): This doesn't work correctly in the case where
                # there was an implicit toplevel import, and an explicit late
                # import, and the moved symbol was used outside the scope of
                # the late import.  To handle this case, we'll need to do much
                # more careful tracing of which imports exist in which scopes.
                add_at = explicit_imports
            else:
                # If not, we add at the first implicit import only.
                first_implicit_localname = min(old_localnames,
                                               key=lambda ln: ln.imp.start)
                add_at = {first_implicit_localname.imp}

            for imp in add_at:
                # Copy the old import's context, such as opening indent
                # and trailing newline.
                # TODO(benkraft): If the context we copy is a comment, and we
                # are keeping the old import, maybe don't copy it?
                start, end = _get_import_area(imp, file_info)
                pre_context = body[start:imp.start]
                post_context = body[imp.end:end]
                # Now we can add the new import and have the same context
                # as the import we are taking the place of!
                text_to_add = ''.join([pre_context, import_stmt, post_context])
                yield khodemod.Patch(filename, '', text_to_add, start, start)

    return suggestor


def import_sort_suggestor(filename, body):
    """Suggestor to fix up imports in a file. `filename` relative to --root."""
    # TODO(benkraft): merge this with the import-adding, so we just show
    # one diff to add in the right place, unless there is additional
    # sorting to do.
    # Now call out to fix_python_imports to do the import-sorting
    change_record = fix_python_imports.ChangeRecord('fake_file.py')

    # A modified version of fix_python_imports.GetFixedFile
    file_line_infos = fix_python_imports.ParseOneFile(
        body, change_record)
    fixed_lines = fix_python_imports.FixFileLines(
        change_record, file_line_infos, FakeOptions())

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


def make_fixes(old_fullname, new_fullname, name_to_import, import_alias=None,
               project_root='.', verbose=False):
    """name_to_import is the module-part of new_fullname."""
    suggestor = fix_uses_suggestor(old_fullname, new_fullname,
                                   name_to_import, import_alias)

    # TODO(benkraft): Support other khodemod frontends.
    frontend = khodemod.AcceptingFrontend(verbose=verbose)

    def log(msg):
        if verbose:
            print msg

    log("===== Updating references =====")
    frontend.run_suggestor(suggestor, root=project_root)

    log("====== Resorting imports ======")
    frontend.run_suggestor_on_modified_files(import_sort_suggestor)

    log("======== Move complete! =======")


def main():
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    # TODO(csilvers): allow moving multiple files into a single directory too.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_fullname')
    parser.add_argument('new_fullname')
    parser.add_argument('-s', '--symbol', action='store_true',
                        help=('Treat moved name as an individual symbol, '
                              'rather than a whole module.'))
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
    # TODO(benkraft): Allow specifying what paths to operate on.
    # TODO(benkraft): Allow specifying explicitly what to import, so we can
    # import a symbol (although KA never wants to do that).
    if parsed_args.symbol:
        name_to_import, _ = parsed_args.new_fullname.rsplit('.', 1)
    else:
        name_to_import = parsed_args.new_fullname

    make_fixes(
        parsed_args.old_fullname, parsed_args.new_fullname, name_to_import,
        import_alias=parsed_args.alias, project_root=parsed_args.root,
        verbose=parsed_args.verbose)


if __name__ == '__main__':
    main()
