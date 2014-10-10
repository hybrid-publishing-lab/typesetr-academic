#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
import unicodedata
import regex as re

from .ezmatch import Var


# pylint: disable=C0103
EN_DASH = unicodedata.lookup('EN DASH')

DASHLIKES = (r'\N{EN DASH}\N{EM DASH}\N{FIGURE DASH}'
             r'\N{HORIZONTAL BAR}'
             r'\N{HYPHEN}\N{HYPHEN-MINUS}\N{HYPHEN BULLET}'
             r'\N{MINUS SIGN}')
NUMBER = r'(?:\d+|m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))'

CITE_REX = re.compile(r'((auto|text)cite)|(cite(author|year|title)p?)$')

PAGE_CITE_REX = re.compile(
    r'^,?\s*pp?\.?\s*(' + NUMBER + r')((?:(?:[\s' +
    DASHLIKES + ',' +
    r']*)(?:(?:pp?\.?\s*)?' + NUMBER + r'))*)$')


# FIXME(alexander): handle stuff like pp.55ff. etc.; parsing page
# abbreviations is probably as stupid idea
def cleanse_post_citation(post):
    ur"""Canonicalize 'pure' page references in a citation 'post'...

    ... also behead  ', '.

    See biblatex manual.

    >>> cleanse_post_citation(['p.60, pp.99-122, 155']) == [u'60, 99–122, 155']
    True
    >>> cleanse_post_citation([', more on that on p.60'])
    ['more on that on p.60']
    >>> print cleanse_post_citation([',   pp. iv-vii, 100'])[0]
    iv–vii, 100
    """
    PAGE_CITE = Var('PAGE_CITE', PAGE_CITE_REX.match)
    if post == [PAGE_CITE]:
        first_page, other_pages = PAGE_CITE.match.groups()
        if not other_pages:
            return [first_page]
        else:
            pages = re.sub(
                r'\s{2,}', ' ',
                re.sub(r'pp?\.?', ' ',
                       re.sub(ur'[' + DASHLIKES + ']+', EN_DASH,
                              first_page + other_pages)))
            return [pages]
    elif post and isinstance(post[0], basestring):
        return [re.sub(r'^,?\s*', '', post[0])] + post[1:]
    else:
        return post
