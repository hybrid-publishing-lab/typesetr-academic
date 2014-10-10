#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-

ur"""Code for making lxml less odious to use.

This module aims to mitigating the .text and .tail specialcasing (rather than
having text nodes) and unicode bugs somewhat.

Lxml is the dominant python xml lib but suffers from countless design flaws:
rather than having dedicated Text nodes, it attaches text only to elements (as
.text for text at the start of the element, and .tail for text beyond the
closing tag). It also does this in a really stupid way: .text and .tail can
also be None instead of '' and can return either str or unicode objects. This
is made even more irritating by the refusal of the functions that go from
basestrings to Elements to work intelligently based on these foibles, for
example Element.extend should just accept a string at the beginning of
extendor and append it the the tail of the last element but doesn't and
unicode/str mixing is also not working, where unicode suppport isn't
completely broken to start with.

Examples:

>>> from lxml import etree

No toplevel element necessary:

>>> ans, = fromstringlist(['lxml'," is a kinda", u' ṳnicodeünaware'," parser"])
>>> print ans
lxml is a kinda ṳnicodeünaware parser

Unicode works and the we can mix string and Element nodes:

>>> frags = ['lxml <b>ṳnicodeünaware</b>', '?']
>>> nodes = fromstringlist(frags)
>>> nodes # doctest: +ELLIPSIS
['lxml ', <Element b at ...>]
>>> etree.tostring(nodes[1])
'<b>&#7795;nicodeu&#776;naware</b>?'

We can also use a mixed list to extend:

>>> top_node, = fromstringlist(['<top/>'])
>>> extend(top_node, nodes)
>>> etree.tostring(top_node)
'<top>lxml <b>&#7795;nicodeu&#776;naware</b>?</top>'

>>> top_node, = fromstringlist(['<top><child/>tail</top>'])
>>> extend(top_node, [' string', 's and 2'] + map(etree.fromstring,
...    ['<element/>']*2))
>>> etree.tostring(top_node)
'<top><child/>tail strings and 2<element/><element/></top>'
""" # "

from lxml import etree
def fromstringlist(xml_frags, ns=''):
    """Parse basestring `s`, using namespace info `ns` if supplied.

    Return a list of of Elements, or a list with one string followed by
    Elements if xml_frags starts with a string.
    """
    # NB: this doesn't use fromstringlist, because it's broken for unicode
    # (according to the docs it just barfs on mixed unicode/strs...
    # ... but in 2.3 it barfs on pure unicode as well)
    e = etree.fromstring('<bogus %s>%s</bogus>' % (
        str(ns), ''.join(xml_frags)))
    children = e.getchildren()
    if e.text:
        children.insert(0, e.text)
    return children

def extend(e, stuff):
    """Like Element.extend, only not retarded...
    ... in that `next(stuff)` can be a basestring.
    """
    assert not isinstance(stuff, basestring), "Can't extend with string"
    stuff = iter(stuff)
    string_parts = []
    try:
        while True:
            first = next(stuff)
            if isinstance(first, basestring):
                string_parts.append(first)
            else:
                if len(e):
                    e[-1].tail = (e[-1].tail or '') + ''.join(string_parts)
                else:
                    e.text = (e.text or '') + ''.join(string_parts)
                e.append(first)
                break
    except StopIteration:
        pass
    e.extend(stuff)
