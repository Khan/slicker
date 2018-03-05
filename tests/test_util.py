from __future__ import absolute_import

import ast
import unittest

from slicker import util


class DottedPrefixTest(unittest.TestCase):
    def test_dotted_starts_with(self):
        self.assertTrue(util.dotted_starts_with('abc', 'abc'))
        self.assertTrue(util.dotted_starts_with('abc.de', 'abc'))
        self.assertTrue(util.dotted_starts_with('abc.de', 'abc.de'))
        self.assertTrue(util.dotted_starts_with('abc.de.fg', 'abc'))
        self.assertTrue(util.dotted_starts_with('abc.de.fg', 'abc.de'))
        self.assertTrue(util.dotted_starts_with('abc.de.fg', 'abc.de.fg'))
        self.assertFalse(util.dotted_starts_with('abc', 'd'))
        self.assertFalse(util.dotted_starts_with('abc', 'ab'))
        self.assertFalse(util.dotted_starts_with('abc', 'abc.de'))
        self.assertFalse(util.dotted_starts_with('abc.de', 'ab'))
        self.assertFalse(util.dotted_starts_with('abc.de', 'abc.d'))
        self.assertFalse(util.dotted_starts_with('abc.de', 'abc.h'))

    def test_dotted_prefixes(self):
        self.assertItemsEqual(
            util.dotted_prefixes('abc'),
            ['abc'])
        self.assertItemsEqual(
            util.dotted_prefixes('abc.def'),
            ['abc', 'abc.def'])
        self.assertItemsEqual(
            util.dotted_prefixes('abc.def.ghi'),
            ['abc', 'abc.def', 'abc.def.ghi'])


class NamesStartingWithTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            set(util.names_starting_with('a', ast.parse('a\n'))),
            {'a'})
        self.assertEqual(
            set(util.names_starting_with(
                'a', ast.parse('a.b.c\n'))),
            {'a.b.c'})
        self.assertEqual(
            set(util.names_starting_with(
                'a', ast.parse('d.e.f\n'))),
            set())

        self.assertEqual(
            set(util.names_starting_with(
                'abc', ast.parse('abc.de\n'))),
            {'abc.de'})
        self.assertEqual(
            set(util.names_starting_with(
                'ab', ast.parse('abc.de\n'))),
            set())

        self.assertEqual(
            set(util.names_starting_with(
                'a', ast.parse('"a.b.c"\n'))),
            set())
        self.assertEqual(
            set(util.names_starting_with(
                'a', ast.parse('import a.b.c\n'))),
            set())
        self.assertEqual(
            set(util.names_starting_with(
                'a', ast.parse('b.c.a.b.c\n'))),
            set())

    def test_in_context(self):
        self.assertEqual(
            set(util.names_starting_with('a', ast.parse(
                'def abc():\n'
                '    if a.b == a.c:\n'
                '        return a.d(a.e + a.f)\n'
                'abc(a.g)\n'))),
            {'a.b', 'a.c', 'a.d', 'a.e', 'a.f', 'a.g'})
