#!/usr/bin/env python
"""Tools to create xml in sexp notation and parse xml strings to sexps.

- FIXME(alexander): canonical ordering of attributes?

- FIXME(alexander): the way I deal with default namespace that also are
  defined as prefixes is not optimal.
"""
from functools import partial

from lxml import etree
XMLSyntaxError = etree.XMLSyntaxError # pylint: disable=C0103

XML_NS = 'http://www.w3.org/XML/1998/namespace'

def de_ns(thing, ns_to_prefix, is_attr=False):
    """Convert ``"{http://example.com}bar"`` to "foo:bar".

    - `ns_to_prefix` is a map of urls to prefixes.
    - `is_attr`: if thing is an attribute, set to true -- namespace
       mapping for attributes works differently than for non-attributes
       in xml, in that no default namespace exists.

    The xml namespace is implicitly supplied:
    >>> de_ns('{http://www.w3.org/XML/1998/namespace}id', {}, is_attr=True)
    'xml:id'

    The default namespace maps to 'None':
    >>> epub_revns = {'http://www.idpf.org/2007/ops': None}
    >>> de_ns('{http://www.idpf.org/2007/ops}type', epub_revns, is_attr=False)
    'type'

    However, for attributes no default namespace exists in xml:
    >>> de_ns('{http://www.idpf.org/2007/ops}type', epub_revns, is_attr=True)
    Traceback (most recent call last):
    ...
    AssertionError: No prefix for ns 'http://www.idpf.org/2007/ops'

    So need to specify an explicit prefix name:
    >>> epub_revns = {'http://www.idpf.org/2007/ops': 'epub'}
    >>> de_ns('{http://www.idpf.org/2007/ops}type', epub_revns, is_attr=True)
    'epub:type'
    """
    if thing[0] != '{':
        return thing
    else:
        ns, raw = thing[1:].split('}')
        prefix = ns_to_prefix[ns] if ns != XML_NS else 'xml'
        if prefix is None:
            assert not is_attr, "No prefix for ns %r" % ns
            return raw
        return '%s:%s' % (prefix, raw)

def re_ns(s, nsmap, is_attr=False):
    """Convert ``"some_ns:thing"`` to ``"{http://some.url}thing."""
    # attributes do *NOT* obey the default namespace
    if is_attr and ':' not in s:
        return s
    prefix, _, localname = s.rpartition(':')
    ns = nsmap.get(prefix or None, '') if prefix != 'xml' else XML_NS
    return '{%s}%s' % (ns, localname)

def _inverted_update(into, source):
    # Take care not to ovewrite non-`None` key with `None`
    # in case of duplicates, so that the default namespaces doesn't clash
    # with attribute namespacing for the same NS.
    into.update((v, k) for (k, v) in source.iteritems() if k is not None)
    if None in source and source[None] not in into:
        into[source[None]] = None
    return into

def _etree2tup(xml, ns_to_prefix):
    """Helper. Mutates `ns_to_prefix`!"""
    _inverted_update(ns_to_prefix, xml.nsmap)
    body = [] if not xml.text else [xml.text]
    body.extend(_etree2tup(e, ns_to_prefix) for e in xml)
    if xml.tail:
        body.append(xml.tail)
    attrs = dict((de_ns(k, ns_to_prefix, is_attr=True), v)
                 for (k, v) in xml.attrib.iteritems())
    return (de_ns(xml.tag, ns_to_prefix), attrs, body)

def etree2tup(xml, ns_to_prefix={}): # pylint: disable=W0102
    """Convert etree xml to a (sexp, ns) tuple.

    `ns_to_prefix` is a map from urls to ns-prefixes to use.
    """
    ns_to_prefix = ns_to_prefix.copy() # mutated below!
    tups = _etree2tup(xml, ns_to_prefix)
    return tups, _inverted_update({None: ''}, ns_to_prefix)

def tup2etree(tup, nsmap={}, mk=None): # pylint: disable=W0102
    """Convert sexp `tup` to etree xml."""
    mk = mk or partial(etree.Element, nsmap=nsmap)
    h, a, b = tup
    xattrs = dict((re_ns(k, nsmap, is_attr=True), v)
                  for (k, v) in a.iteritems())
    e = mk(re_ns(h, nsmap), xattrs, nsmap=nsmap)
    if not b:
        return e
    b = b[:]
    if isinstance(b[0], basestring):
        e.text = b.pop(0)
    if b and isinstance(b[-1], basestring):
        e.tail = b.pop(-1)
    for x in b:
        tup2etree(x, nsmap, partial(etree.SubElement, e))
    return e

def to_etree(f_or_s, strip=True, **kwargs):
    """Convert xml string or file handle `f_or_s` to etree xml.

    `strip` = cull whitespace (default = true)
    """
    parser = etree.XMLParser(remove_comments=True, remove_blank_text=strip,
                             **kwargs)
    if isinstance(f_or_s, basestring):
        return etree.fromstring(f_or_s, parser)
    return etree.parse(f_or_s, parser)

def etree2s(xml, pretty=True, decl=False, html=False, cleanup=True):
    """Convert etree `xml` to a string representation.

    `decl=True` adds ``<?xml version="1.0" ... ?>`` to the output
    `html=True` adds ``<!DOCTYPE html>``, and must be used with `decl=True`.
    """
    if cleanup:
        etree.cleanup_namespaces(xml)
    ans = etree.tostring(xml,
                         pretty_print=pretty, encoding='UTF-8',
                         xml_declaration=decl)
    if html:
        assert decl
        ans = ans.replace('?>', '?>\n<!DOCTYPE html>', 1)
    # always force unicode or str?
    if isinstance(ans, unicode):
        ans = ans.encode('utf-8')
    return ans

def tup2xml(tup, nsmap={}, **kwargs): # pylint: disable=W0102
    """Convert `tup` to an xml-string with optional `nsmap`.
    """
    return etree2s(tup2etree(tup, nsmap=nsmap), **kwargs)

def xml2tup(s, strip=True):
    r"""Convert an xml string to a sexp plus NS dictionary.

    >>> from pprint import pprint

    space is stripped by default:
    >>> pprint(xml2tup('''<x>
    ...                    <y/>
    ...                 </x>'''))
    (('x', {}, [('y', {}, [])]), {None: ''})

    unless xml:space is set on an outer element...
    >>> pprint(xml2tup('''<x xml:space='preserve'>
    ...                    <y/>
    ...                 </x>'''))
    (('x',
      {'xml:space': 'preserve'},
      ['\n                   ', ('y', {}, ['\n                '])]),
     {None: ''})

    ... or strip=False is set:
    >>> xml2tup('''<x>   <y/></x>''', strip=False)
    (('x', {}, ['   ', ('y', {}, [])]), {None: ''})
    """

    return etree2tup(to_etree(s, strip=strip))
