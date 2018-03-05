"""Logic to replace references to a name in a file.

This file doesn't deal with imports -- it's just about replacing the actual
references in the file, for some given set of localnames.  See the main
entrypoint, replace_in_file, for more.
"""
from __future__ import absolute_import

import ast
import re
import string
import tokenize

from . import khodemod
from . import util


_FILENAME_EXTENSIONS = ('.py', '.js', '.jsx', '.png', '.jpg', '.svg', '.html',
                        '.less', '.handlebars', '.json', '.txt', '.css')
_FILENAME_EXTENSIONS_RE_STRING = '|'.join(re.escape(e)
                                          for e in _FILENAME_EXTENSIONS)


def _re_for_name(name):
    """Find a dotted-name (a.b.c) given that Python allows whitespace.

    This is actually pretty tricky.  Here are some issues:
    1) We don't want a name `a.b.c` to match `d.a.b.c`.
    2) We don't want a name `foo` to match `foo.py` -- that's a filename,
       not a module-name (and is handled separately).  We also don't
       want it to match other common filename extensions.
    3) We don't want a name `browser` to match text like
       "# Open a new browser window"

    The first two issues are easy to handle.  For the third, we add a
    special case for "English-seeming" names: those that have only
    alphabetic chars.  For those words, we only rename them if they're
    followed by a dot (which could be module.function) or match
    the entire string (which could be a mock or some other literal
    use).  We also allow surrounded-by-backticks, since that's
    markup-language for "code".
    """
    # TODO(csilvers): replace '\s*' by '\s*#\s*' below, and then we
    # can use this to match line-broken dotted-names inside comments too!
    name_with_spaces = re.escape(name).replace(r'\.', r'\s*\.\s*')
    if not name.strip(string.ascii_letters):
        # Name is entirely alphabetic.
        return re.compile(r'(?<!\.)\b%s(?=\.\w)(?!%s)|^%s$|(?<=`)%s(?=`)'
                          % (name_with_spaces, _FILENAME_EXTENSIONS_RE_STRING,
                             name_with_spaces, name_with_spaces))
    else:
        return re.compile(r'(?<!\.)\b%s\b(?!%s)'
                          % (name_with_spaces, _FILENAME_EXTENSIONS_RE_STRING))


def _re_for_path(path):
    """Find a filename path that matches this path.

    Note we do not match supersets of the path, so if path is
    a/b/c.py we do not match d/a/b/c.py.
    """
    return re.compile(r'(?<!/)\b%s\b' % re.escape(path))


def _replace_in_string(node, regex, replacement, file_info):
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
        node: an ast.Str node
        regex: a compiled regex object
        replacement: a string to replace with (note we do not support \1-style
            references)
        file_info: the file to do the replacements in.

    Returns: a generator of khodemod.Patch objects.
    """
    if not regex.search(node.s):
        # The regex didn't match at all; no need to do further work.
        return

    str_tokens = file_info.tokens.get_tokens(node, include_extra=True)
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


def replace_in_file(file_info, old_fullname, old_localnames,
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
                util.names_starting_with(localname, node_to_fix).iteritems()):
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
            _re_for_path(util.filename_for_module_name(old_fullname)),
            util.filename_for_module_name(new_fullname)))
    for localname in old_localnames - {new_localname, old_fullname}:
        # For code like `from flags import flags`, If we see text like
        # `mock('flags.flags.myfunc')`, it's ambiguous: does this mean
        # flags.flags.myfunc or flags.flags.flags.myfunc?  Both are
        # possible in this weird "package and module share a name"
        # scenario.  Obviously, the first one is the proper
        # interpretation, so we only want the regexp matching
        # flags.flags, not plain 'flags', in this case.
        if not util.dotted_starts_with(old_fullname, localname):
            regexes_to_check.append((_re_for_name(localname), new_localname))

    # Strings
    for node in ast.walk(node_to_fix):
        if isinstance(node, ast.Str):
            # We compute str_tokens only if any of the regexes match
            for regex, replacement in regexes_to_check:
                patches.extend(
                    _replace_in_string(node, regex, replacement, file_info))

    # Comments
    # HACK: to avoid touching file_info.tokens unnecessarily, which is slow, we
    # first check to see if the regexes appear *anywhere* in the body.  If not,
    # they certainly can't be in a comment!  So we skip the extra parsing.
    for regex, replacement in regexes_to_check:
        if regex.search(file_info.body):
            break
    else:
        return patches, used_localnames

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
