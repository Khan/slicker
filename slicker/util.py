from __future__ import absolute_import

import ast
import os
import tokenize

import asttokens

from . import khodemod
from . import unicode_util


def filename_for_module_name(module_name):
    """filename is relative to a sys.path entry, such as your project-root."""
    return '%s.py' % module_name.replace('.', os.sep)


def module_name_for_filename(filename):
    """filename is relative to a sys.path entry, such as your project-root."""
    return os.path.splitext(filename)[0].replace(os.sep, '.')


class File(object):
    """Represents information about a file.

    TODO(benkraft): Also cache things like _compute_all_imports.
    """
    def __init__(self, filename, body):
        """filename is relative to the value of --root."""
        self.filename = filename
        self.body = body
        self._tree = None    # computed lazily
        self._tokens = None  # computed lazily

    @property
    def tree(self):
        """The AST for the file.  Computed lazily on first use."""
        if self._tree is None:
            try:
                # ast.parse would really prefer to run on bytes.
                # Luckily we ignore all of the (useless) line/col
                # information in the AST nodes -- we get it via
                # asttokens instead -- so we don't have to worry
                # about the fact that these will be byte offsets.
                self._tree = ast.parse(
                    unicode_util.encode(self.filename, self.body))
            except SyntaxError as e:
                raise khodemod.FatalError(self.filename, 0,
                                          "Couldn't parse this file: %s" % e)
        return self._tree

    @property
    def tokens(self):
        """The asttokens.ASTTokens mapping for the file.

        This is computed lazily on first use, and is somewhat slow to compute,
        so we try to only use it when we need to (i.e. on files we are
        editing).
        """
        if self._tokens is None:
            self._tokens = asttokens.ASTTokens(self.body, tree=self.tree)
        return self._tokens

    def __repr__(self):
        return "File(filename=%r)" % self.filename


def is_newline(token):
    # I think this is equivalent to doing
    #      token.type in (tokenize.NEWLINE, tokenize.NL)
    # TODO(benkraft): We don't really handle files with windows newlines
    # correctly -- any newlines we add will be wrong.  Do the right thing.
    return token.string in ('\n', '\r\n')


def get_area_for_ast_node(node, file_info, include_previous_comments):
    """Return the start/end character offsets of the input ast-node + friends.

    We include every line that node spans, as well as their ending newlines,
    though if the last line has a semicolon we end at the semicolon.

    If include_previous_comments is True, we also include all comments
    and newlines that directly precede the given node.
    """
    toks = list(file_info.tokens.get_tokens(node, include_extra=True))
    first_tok = toks[0]
    last_tok = toks[-1]

    if include_previous_comments:
        for istart in xrange(first_tok.index - 1, -1, -1):
            tok = file_info.tokens.tokens[istart]
            if (tok.string and not tok.type == tokenize.COMMENT
                    and not tok.string.isspace()):
                break
        else:
            istart = -1
    else:
        for istart in xrange(first_tok.index - 1, -1, -1):
            tok = file_info.tokens.tokens[istart]
            if tok.string and (is_newline(tok) or not tok.string.isspace()):
                break
        else:
            istart = -1

    # We don't want the *very* earliest newline before us to be
    # part of our context: it's ending the previous statement.
    if istart >= 0 and is_newline(file_info.tokens.tokens[istart + 1]):
        istart += 1

    prev_tok_endpos = (file_info.tokens.tokens[istart].endpos
                       if istart >= 0 else 0)

    # Figure out how much of the last line to keep.
    for tok in file_info.tokens.tokens[last_tok.index + 1:]:
        if tok.type == tokenize.COMMENT:
            last_tok = tok
        elif is_newline(tok):
            last_tok = tok
            break
        else:
            break

    return (prev_tok_endpos, last_tok.endpos)


def toplevel_names(file_info):
    """Return a dict of name -> AST node with toplevel definitions in the file.

    This includes function definitions, class definitions, and constants.
    """
    # TODO(csilvers): traverse try/except, for, etc, and complain
    # if we see the symbol defined inside there.
    # TODO(benkraft): Figure out how to handle ast.AugAssign (+=) and multiple
    # assignments like `a, b = x, y`.
    retval = {}
    for top_level_stmt in file_info.tree.body:
        if isinstance(top_level_stmt, (ast.FunctionDef, ast.ClassDef)):
            retval[top_level_stmt.name] = top_level_stmt
        elif isinstance(top_level_stmt, ast.Assign):
            # Ignore assignments like 'a, b = x, y', and 'x.y = 5'
            if (len(top_level_stmt.targets) == 1 and
                    isinstance(top_level_stmt.targets[0], ast.Name)):
                retval[top_level_stmt.targets[0].id] = top_level_stmt
    return retval
