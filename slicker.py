#!/usr/bin/env python
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
    return re.compile(r'(?<!\.)\b%s\b' %
                      re.escape(name).replace(r'\.', r'\s*\.\s*'))


class FakeOptions(object):
    safe_headers = True


# Import: an import in the file (or a part thereof, if commas are used).
#   name: the fully-qualified symbol we imported.
#   alias: the name under which we imported it.
#   start, end: character-indexes delimiting the import
#   node: the AST node for the import.
# So for example, 'from foo import bar' would result in an Import with
# name='foo.bar' and alias='bar'.  If it were at the start of the file it would
# have start=0, end=19.  See test cases for more examples.
Import = collections.namedtuple(
    'Import', ['name', 'alias', 'start', 'end', 'node'])

# SymbolImport: an import, plus the context for a symbol it brings.
#   imp: the Import that makes this symbol available
#   symbol: the symbol we are looking for
#   alias: the name under which the symbol is made available.
# So in the above example, if we were searching for foo.bar.some_function(),
# we'd get a SymbolImport with symbol='foo.bar.some_function' and
# alias='bar.some_function'.  See test cases for more examples.
SymbolImport = collections.namedtuple(
    'SymbolImport', ['imp', 'symbol', 'alias'])


def _compute_all_imports(body):
    """Returns info about the imports in this file.

    Returns a set of Import objects.
    """
    try:
        # TODO(benkraft): cache the AST.
        root = ast.parse(body)
        tokens = asttokens.ASTTokens(body, tree=root)
    except SyntaxError:
        return set()
    imports = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            if isinstance(node, ast.ImportFrom) and node.level != 0:
                # TODO(benkraft): Figure out how to handle these!  It's
                # unfortunately tricky for us to get the filename we're working
                # on, so we just ignore them and cross our fingers for now.
                continue
            start, end = tokens.get_text_range(node)
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


def _determine_imports(symbol, body):
    """Returns info about the names by which the symbol goes in this file.

    Returns a set of SymbolImport namedtuples.
    """
    imports = set()
    symbol_parts = symbol.split('.')
    for imp in _compute_all_imports(body):
        imported_parts = imp.name.split('.')
        if imp.alias == imp.name:
            if imported_parts[0] == symbol_parts[0]:
                imports.add(SymbolImport(imp, symbol, symbol))
        else:
            nparts = len(imported_parts)
            # If we imported the symbol, or a less-specific prefix (e.g. its
            # module, or a parent of that)
            if symbol_parts[:nparts] == imported_parts:
                symbol_alias = '.'.join(
                    [imp.alias] + symbol_parts[nparts:])
                imports.add(SymbolImport(imp, symbol, symbol_alias))
    return imports


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


def _name_for_node(node):
    """Return the dotted name of an AST node, if there's a reasonable one.

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
    """Returns all names in the file.

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


def _names_starting_with(prefix, body):
    """Returns all dotted names in the file beginning with 'prefix'.

    Does not include imports or string references or anything else funky like
    that.  "Beginning with prefix" in the dotted sense (see
    _dotted_starts_with).

    Returns a dict of name -> list of nodes.
    """
    root = ast.parse(body)
    # Add token metadata.  TODO(benkraft): pass things around to avoid this
    # side effect.
    asttokens.ASTTokens(body, tree=root)
    retval = {}
    for name, node in _all_names(root):
        if _dotted_starts_with(name, prefix):
            retval.setdefault(name, []).append(node)
    return retval


def _check_import_conflicts(body, added_name, is_alias):
    """Return any imports that will conflict with ours.

    added_name should be the name of the import, not the symbol.
    Returns a list of import objects.

    TODO(benkraft): If that's due to our alias, we could avoid using
    said alias.
    TODO(benkraft): Also check if there are variable-names that
    collide.
    """
    imports = _compute_all_imports(body)
    if is_alias:
        # If we are importing with an alias, we're looking for existing
        # imports with whose prefix we collide.
        return {imp for imp in imports
                if _dotted_starts_with(imp.alias, added_name)}
    else:
        # If we aren't importing with an alias, we're looking for
        # existing imports who are a prefix of us.
        return {imp for imp in imports
                if _dotted_starts_with(added_name, imp.alias)}


def _imports_to_remove(old_imports, new_name, patched_aliases, body):
    """Decide what imports we can remove.

    Arguments:
        old_imports: set of SymbolImports
        new_name: the name to which we moved the symbol
        patched_aliases: the set of SymbolImports whose references we
        potentially patched
        body: the file text

    returns: (set of imports we can remove,
              set of imports that may be used implicitly)
    """
    # Decide whether to keep the old import if we changed references to it.
    removable_imports = set()
    maybe_removable_imports = set()
    definitely_kept_imports = set()
    for imp in old_imports:
        if new_name == imp.alias:
            # If one of the old imports is for the same alias, it had
            # better be removable!  (We've already checked for conflicts.)
            removable_imports.add(imp.imp)
        elif imp.alias in patched_aliases:
            # Anything starting with the relevant prefix.
            relevant_names = set(_names_starting_with(
                imp.imp.alias.split('.')[0], body))
            handled_names = {
                name for name in relevant_names
                if _dotted_starts_with(name, imp.alias)}
            explicit_names = {
                name for name in relevant_names
                if _dotted_starts_with(name, imp.imp.alias)}

            # If we reference this import, other than for the moved symbol, we
            # may need to keep it.
            if explicit_names - handled_names:
                definitely_kept_imports.add(imp.imp)
            elif relevant_names - handled_names:
                maybe_removable_imports.add(imp.imp)
            else:
                removable_imports.add(imp.imp)
        else:
            definitely_kept_imports.add(imp.imp)

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

    return removable_imports, maybe_removable_imports


def _get_import_area(imp, tokens):
    """Return the start/end character offsets of the whole import region.

    We include everything that is part of the same line, as well as its ending
    newline, (but excluding semicolons), as part of the import region.

    TODO(benkraft): Should we look at preceding full-line comments?  We end up
    fighting with fix_python_imports if we do.
    """
    toks = list(tokens.get_tokens(imp.node, include_extra=True))
    first_tok = toks[0]
    last_tok = toks[-1]

    # prev_tok will be the last token before the import area, or None if there
    # isn't one.
    prev_tok = next(reversed(
        [tok for tok in tokens.tokens[:first_tok.index]
         if tok.string == '\n' or not tok.string.isspace()]), None)

    for tok in tokens.tokens[last_tok.index + 1:]:
        if tok.type == tokenize.COMMENT:
            last_tok = tok
        elif tok.string == '\n':
            last_tok = tok
            break
        else:
            break

    return (prev_tok.endpos if prev_tok else 0, last_tok.endpos)


def the_suggestor(old_name, new_name, name_to_import, use_alias=None):
    def suggestor(filename, body):
        # TODO(benkraft): cache the AST.
        tokens = asttokens.ASTTokens(body, parse=True)

        # PART THE FIRST:
        #    Set things up, do some simple checks, decide whether to operate.

        # TODO(benkraft): This is super ginormous by now, break it up.
        assert _dotted_starts_with(new_name, name_to_import), (
            "%s isn't a valid name to import -- not a prefix of %s" % (
                name_to_import, new_name))

        old_imports = _determine_imports(old_name, body)
        # Choose the alias to replace with.
        # TODO(benkraft): this might not be totally safe if the existing
        # import isn't toplevel, but probably it will be.
        existing_new_imports = {
            imp.alias for imp
            in _determine_imports(new_name, body)
            if name_to_import == imp.imp.name}

        # If we didn't import the module at all, nothing to do.
        # TODO(benkraft): We should still look for mocks and such here.
        if not old_imports:
            return

        old_aliases = {imp.alias for imp in old_imports}

        # If for some reason there are multiple existing aliases
        # (unlikely), choose the shortest one, to save us line-wrapping.
        # Prefer an existing explicit import to the caller-provided alias.
        if existing_new_imports:
            final_new_name = max(existing_new_imports, key=len)
        elif use_alias and name_to_import == new_name:
            final_new_name = use_alias
        elif use_alias:
            final_new_name = '%s.%s' % (
                use_alias, new_name[len(name_to_import) + 1:])
        else:
            final_new_name = new_name

        if not existing_new_imports:
            dupe_imports = _check_import_conflicts(
                body, use_alias or name_to_import, bool(use_alias))
            if dupe_imports:
                raise khodemod.FatalError(
                    dupe_imports.pop().start,
                    "Your alias will conflict with imports in this file.")

        # PART THE SECOND:
        #    Patch references to the symbol inline -- everything but imports.

        patched_aliases = set()
        # If any alias changed, we need to fix up references.  (We'll fix
        # up imports either way at this point.)
        for imp in old_aliases - {final_new_name}:
            for name, nodes in _names_starting_with(imp, body).iteritems():
                for node in nodes:
                    start, end = tokens.get_text_range(node)
                    patched_aliases.add(imp)
                    yield khodemod.Patch(
                        body[start:end], final_new_name + name[len(imp):],
                        start, end)

        # PART THE THIRD:
        #    Add/remove imports, if necessary.

        # Nor if we didn't fix up references and would have had to.
        # TODO(benkraft): I think we do extra work here if we don't change the
        # alias but also don't have any references.
        if not patched_aliases and final_new_name not in old_aliases:
            return

        removable_imports, maybe_removable_imports = _imports_to_remove(
            old_imports, final_new_name, patched_aliases, body)

        if (existing_new_imports and not removable_imports and
                not maybe_removable_imports):
            # We made changes, but still don't need to fix any imports.
            return

        for imp in maybe_removable_imports:
            yield khodemod.WarningInfo(
                imp.start, "This import may be used implicitly.")
        for imp in removable_imports:
            toks = list(tokens.get_tokens(imp.node, include_extra=False))
            next_tok = tokens.next_token(toks[-1], include_extra=True)
            if next_tok.type == tokenize.COMMENT and (
                    '@nolint' in next_tok.string.lower() or
                    '@unusedimport' in next_tok.string.lower()):
                # Don't touch nolinted imports; they may be there for a reason.
                yield khodemod.WarningInfo(
                    imp.start, "Not removing import with @Nolint.")
            elif ',' in body[imp.start:imp.end]:
                # TODO(benkraft): How should this consider internal comments?
                yield khodemod.WarningInfo(
                    imp.start, "I don't know how to edit this import.")
            else:
                start, end = _get_import_area(imp, tokens)
                yield khodemod.Patch(body[start:end], '', start, end)

        # Consider whether to add an import.
        if not existing_new_imports:
            # Decide what the import will say.
            if '.' in name_to_import and use_alias:
                base, suffix = name_to_import.rsplit('.', 1)
                if use_alias == suffix:
                    import_stmt = 'from %s import %s' % (base, suffix)
                else:
                    import_stmt = 'import %s as %s' % (
                        name_to_import, use_alias)
            else:
                if use_alias and use_alias != name_to_import:
                    import_stmt = 'import %s as %s' % (
                        name_to_import, use_alias)
                else:
                    import_stmt = 'import %s' % name_to_import

            # Decide where to add it.
            explicit_imports = {imp for imp in old_imports
                                # TODO(benkraft): This is too weak -- we should
                                # only call an import explicit if it is of the
                                # symbol's module.
                                if _dotted_starts_with(old_name, imp.imp.name)}

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
                add_at = next(sorted(old_imports,
                                     key=lambda imp: imp.imp.start))

            for imp in add_at:
                # Copy the old import's context.
                # TODO(benkraft): If the context we copy is a comment, and we
                # are keeping the old import, maybe don't copy it?
                start, end = _get_import_area(imp.imp, tokens)
                text_to_add = ''.join(
                    [body[start:imp.imp.start],
                     import_stmt,
                     body[imp.imp.end:end]])

                yield khodemod.Patch('', text_to_add, start, start)

    return suggestor


def import_sort_suggestor(filename, body):
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
            yield khodemod.Patch(body[i1:i2], fixed_body[j1:j2], i1, i2)


def main():
    # TODO(benkraft): Allow moving multiple symbols (from/to the same modules)
    # at once.
    parser = argparse.ArgumentParser()
    parser.add_argument('old_name')
    parser.add_argument('new_name')
    parser.add_argument('-m', '--module', action='store_true',
                        help=('Treat moved name as a module, rather than a '
                              'symbol.'))
    # TODO(benkraft): We don't handle mocks right when there is an alias.
    parser.add_argument('-a', '--alias', metavar='ALIAS',
                        help=('Alias to use when adding new import lines.'
                              'If this has a dot (e.g. it is a symbol, not a '
                              'module), all parts except the first must match '
                              'the real name.'))
    parsed_args = parser.parse_args()
    # TODO(benkraft): Allow specifying what paths to operate on.
    # TODO(benkraft): Allow specifying explicitly what to import, so we can
    # import a symbol (although KA never wants to do that).
    if parsed_args.module:
        name_to_import = parsed_args.new_name
    else:
        name_to_import, _ = parsed_args.new_name.rsplit('.', 1)
    suggestor = the_suggestor(parsed_args.old_name, parsed_args.new_name,
                              name_to_import, use_alias=parsed_args.alias)
    # TODO(benkraft): Support other khodemod frontends.
    khodemod.SilentFrontend().run_suggestor(suggestor)
    khodemod.SilentFrontend().run_suggestor(import_sort_suggestor)


if __name__ == '__main__':
    main()
