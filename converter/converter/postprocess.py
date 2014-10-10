#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
"""Tools for postprocessing the first pass parse fo odt to internal repr.

Google docs generated ODT has a number of deficiencies, this module contains a
bunch of routines to post-process the internal representation generated from
odt xml into something that negates. The defects of Google docs generated ODT
include:

- lots of bloat, e.g:

  - `<b>some bold words and <i>italic</i> text</b>` is represented roughly
    like so: `<span ...>some</span><sp/><span ...>bold</span> ...` worse, they
    even do this on links (each word becomes a separate link) and because
    that's apparently not bad enough yet, each link also contains at least one
    span, which is sets the text color to blue (argh).

  - spaces and tabs are explicitly marked up.

- no support for a number of important semantic elements that thus need to be
  inferred

  - proper figures (no support for captions or floating); no support for
    sizing figures in a precise or meaningful way (that's an UI issue, but we
    need to deal with this at the format level by implementing snapping). No
    support for scalable or high-res bitmap figures

  - proper tables (no support for headings, captions or floating)

"""

from collections import OrderedDict
import copy
from itertools import groupby
import logging as log
import unicodedata

import regex as re

from converter.ezmatch import Var, Seq
from converter.internal import (
    mkel, mkerr, mkcmd, mklit, varcmd, varlit, varel,
    INLINE_TAG, H_TAGS, BLOCK_TAGS, NON_EMPTY_BLOCK_TAGS, FULLY_VOID_TAGS)
from converter import literal
from converter.citations import cleanse_post_citation
from converter.docerror import docproblem
from converter.html_parser import parse_chunk


#pylint: disable=C0103

CAN_OCCUR_IN_H = ('a', '.footnote', 'aside', 'code',
                  # allow underlining, to ensure we don't strip out CMDs and
                  # LITs in headings before we get around to calling
                  # `underlines_to_commands` on the heading
                  'u', 'CMD', 'LIT',
                  # margin figures
                  'figure', 'img')

def window(seq, n):
    w = [None] * n
    for x in seq:
        w.pop(0)
        w.append(x)
        yield tuple(w)

# XXX: the fact that this works on both bodies and elements
# is a bit unprincipled, but convenient
# the list of NEVER_BLANK elements needs to be maintained
NEVER_BLANK = ('figure', 'img', 'CMD', 'LIT', '.pagebreak')
def blank(thing):
    r"""Is the element or body `thing` content-free?

    >>> blank(' ') and blank(['\t']) and blank(('a', {'name': 'some link'}, []))
    True
    >>> blank('x') or blank(('img', {'src': 'foo.png'}, []))
    False
    >>> blank(('a', {'href': 'foo.html'}, ['', ('span', {}, '')]))
    True
    >>> blank(('a', {'href': 'some link'}, ['', ('span', {}, 'link text')]))
    False
    """
    if isinstance(thing, basestring):
        return not thing.strip()
    elif isinstance(thing, tuple):
        h, _, b = thing
        return h not in NEVER_BLANK and blank(b)
    else:
        return all(blank(e) for e in thing)

def non_blank(thing):
    return not blank(thing)

def plaintextify(body):
    """
    >>> plaintextify([('h1', {},
    ...                [('a', {'name': 'h.5kvjtksy022i'}, []),
    ...                 'This is a level 1 ', ('b', {}, ['heading']),
    ...                 ' with comment',
    ...                 ('.footnote', {}, ['And a footnote.'])])])
    'This is a level 1 heading with comment'
    """
    assert isinstance(body, list)
    ans = tidy(whack(bool, whack('.footnote'.__eq__, body, True)))
    if len(ans) == 0:
        return ''
    assert len(ans) == 1, "plaintextify broke"
    return ans[0]

def whack(pred, body, kill_body=False):
    r"""Recursively splice elements in `body` whose tag fulfills `pred`.

    >>> text = [('a', {}, [('b', {}, ['bold1'])]), ('b', {}, ['bold2'])]
    >>> whack('b'.__eq__, text)        # de-bold
    [('a', {}, ['bold1']), 'bold2']
    >>> whack('b'.__eq__, text, True)  # kill rather than splice
    [('a', {}, [])]
    """
    return whack_elt(lambda e: pred(e[0]), body, kill_body)

def whack_elt(pred, body, kill_body=False):
    res = []
    for e in body:
        if isinstance(e, basestring):
            res.append(e)
        else:
            bh, ba, bb = e
            if pred(e):
                if not kill_body:
                    res.extend(whack_elt(pred, bb, kill_body))
            else:
                res.append(mkel(bh, ba, whack_elt(pred, bb, kill_body)))
    return res


def _sib_bodies(groups):
    return (e for g in groups for e in g[2])

def _coalesce_siblings(tag, attrs, sibling_group):
    compacted_content = tidy(_sib_bodies(sibling_group))
    if (tag, attrs) == ('span', {}):
        for compacted_bit in compacted_content:
            yield compacted_bit
    else:
        yield mkel(tag, attrs, compacted_content)


def needs_wrapping_in_p(body):
    REAL_BLOCK_TAG = Var('REAL_BLOCK_TAG',
                         lambda e: e in BLOCK_TAGS and e != '.footnote')
    _ = Var('_')
    if body == [(REAL_BLOCK_TAG, _, _)]:
        return False
    else:
        # if we're too eager to wrap things in p's then hopefully a subsequent
        # tidy pass will remove them
        return True


# FIXME(alexander): .block -> pre | blockquote handling
# hacky and limited ATM; no support for nesting etc.
def _coalesce_blocks(attrs, blocks):
    B = Var('B')
    _ = Var('_')
    blocks = list(blocks)
    _debug = blocks[:]
    def next_body():
        return blocks.pop(0)[2] if blocks else []
    while True:
        body = next_body()
        if not body:
            break
        pre_block = []
        while body and body == [('code', {}, B)]:
            pre_block.append(plaintextify(B.val) + '\n')
            body = next_body()
        if pre_block:
            pre_block = mkel('pre', {}, pre_block)
            yield pre_block
        non_pre_block = []
        while body and body != [('code', {}, B)]:
            is_citation = 'right' in attrs.get('class', [])
            if is_citation:
                non_pre_block.append(mkel('footer', {},
                                          [mkel('cite', {}, body)]))
            else:
                if needs_wrapping_in_p(body):
                    body = [mkel('p', {}, body)]
                non_pre_block.extend(body)
            body = next_body()

        if non_pre_block:
            yield mkel('blockquote', {}, tidy(non_pre_block))

def _style_merge(attrs, style):
    """Nondestructively merge `style` into `attrs`, preferring former."""
    attrs = copy.copy(attrs)
    attrs.setdefault('style', OrderedDict()).update(style)
    return attrs

def is_space(x):
    return isinstance(x, basestring) and not x.strip()

def is_p(elt):
    return elt[:1] == ('p',)

def _coalesce_parent_child(parent):
    # the tidy below is
    tag, attrs, raw_body = parent
    body = tidy(raw_body)
    B = Var('B')
    # rationale:
    #     <li>
    #       <p>a</p>
    #       <ul>...</ul>
    #     </li>
    # should be transformed to:
    #     <li>
    #       a
    #       <ul>...</ul>
    #     </li>
    DOES_NOT_START_WITH_P = Var('DOES_NOT_START_WITH_P',
                                lambda elts: not any(is_p(elt) for elt in elts))
    BODY_WITH_BOGUS_P = Seq[('p', {}, B), DOES_NOT_START_WITH_P:]
    # google docs inserts paragraphs at the darnest places
    # unwrap singleton paragraphs where they don't belong
    # XXX(alexander): consider lifting p attributes
    # like justify class in comprehensive-test
    if tag in ('li', 'dt', 'dd', '.footnote') and body == BODY_WITH_BOGUS_P:
        body = B.val + DOES_NOT_START_WITH_P.val
    elif (tag, attrs) == ('p', {}) and body in (
            [('.pagebreak', {}, [])],
            [('blockquote', {}, B)]):
        (tag, attrs, body), = body
    else:
        LIFTABLE_SPAN_STYLE = Var(
            'LIFTABLE_SPAN_STYLE',
            lambda d: not (set(d) - ({'color', 'background-color'} -
                                     set(attrs.get('style', {})))))
        if body == [('span', {'style': LIFTABLE_SPAN_STYLE}, B)]:
            body = B.val
            attrs = _style_merge(attrs, LIFTABLE_SPAN_STYLE.val)
    return mkel(tag, attrs, body)

def _tidy_heading(tag, attrs, body):
    # is there any actual textual content in the heading?
    cleansed = tidy(whack(lambda e: e not in CAN_OCCUR_IN_H, body))
    if not blank(whack(lambda e: e in ('img', 'figure'), cleansed)):
        yield tag, {k:v for k, v in attrs.iteritems() if k != 'style'}, cleansed
        return
    # no, so it's not really a heading
    # but maybe it contains some misformatted figures or similar
    # so yield the contents that aren't anchors or whitespace strings
    _, _STRING = Var('_'), Var('_STRING', isinstance, basestring)
    for x in cleansed:
        if x != ('a', {'name': _}, []) and x != _STRING:
            yield x

def nfc(s):
    return s if type(s) is str else unicodedata.normalize('NFC', s)

def coalesce(es): # pylint: disable=R0912,R0914
    def grouper(thing):
        if isinstance(thing, basestring):
            return basestring
        else:
            return thing[:2]
    EMPTY_NON_VOID_ELEMENT = (Var('_', lambda tag: tag not in FULLY_VOID_TAGS),
                              {}, [])
    EMPTY_BLOCK_ELEMENT = (Var('_', NON_EMPTY_BLOCK_TAGS.__contains__),
                           Var('_'),
                           [Var('_', blank)])
    EMPTY_LINK = ('a', Var('ATTRS', lambda a: 'name' not in a), [])
    BOGUS_ELEMENTS = (EMPTY_NON_VOID_ELEMENT, EMPTY_BLOCK_ELEMENT, EMPTY_LINK)
    for (tag_attrs, group) in groupby(es, grouper):
        if tag_attrs is basestring:
            yield nfc("".join(group))
        else:
            tag, attrs = tag_attrs
            if tag in INLINE_TAG or tag == 'blockquote':
                for x in _coalesce_siblings(tag, attrs, group):
                    if x not in BOGUS_ELEMENTS:
                        yield x
            elif tag == '.block':
                for x in _coalesce_blocks(attrs, group):
                    yield x
            # FIXME(alexander): don't simplify CMD and LIT contents for now...
            # ... this is needed because of the stupid representation of
            # citations, in particular
            elif tag in ('LIT', 'CMD'):
                for x in group:
                    yield x
            else:
                for x in (_coalesce_parent_child(parent) for parent in group):
                    if x in BOGUS_ELEMENTS:
                        continue
                    if tag in H_TAGS:
                        for y in _tidy_heading(*x):
                            yield y
                    else:
                        yield x


def tidy(es):
    return list(coalesce(es))


def _space_normalize1(e, lstrip=False, rstrip=False):
    if isinstance(e, basestring):
        s = re.sub(r'[\n\r\t ]+', ' ', e)
        if lstrip:
            s = s.lstrip()
        if rstrip:
            s = s.rstrip()
        return (s, not s and lstrip or bool(re.search('[\n\r\t ]$', s)))
    elif e[:1] == ('pre', ):
        return (e, True)
    else:
        h, a, b = e
        block_el = h in BLOCK_TAGS
        new_b, lstrip = _space_normalize(b, lstrip, rstrip, block_el)
        lstrip = lstrip or block_el and h != '.footnote'
        return (mkel(h, a, new_b), lstrip)

def _space_normalize(es, lstrip=False, rstrip=False, parent_was_block_el=False):
    REAL_BLOCK_TAG = Var('REAL_BLOCK_TAG',
                         lambda e: e in BLOCK_TAGS and e != '.footnote')
    _ = Var('_')
    ans = []
    n = len(es)
    for i, e in enumerate(es):
        new_e, lstrip = _space_normalize1(
            e,
            # NB: the parenthesization difference is intentional
            lstrip=lstrip or parent_was_block_el and i == 0,
            rstrip=(rstrip or parent_was_block_el) and i == n-1 or (
                es[i+1:i+2] == [(REAL_BLOCK_TAG, _, _)]))
        if new_e:
            ans.append(new_e)
    return ans, lstrip

def space_normalize(es):
    r"""Canonicalize whitespace in elements `es`.

    Outside pre's all space is folded.
    >>> from pprint import pprint as pp
    >>> space_normalize(['2  spaces:  ', ('pre', {}, ['   x\n y\n']), ' here.'])
    ['2 spaces:', ('pre', {}, ['   x\n y\n']), 'here.']

    Block Elements and have their inner text stripped and leading and trailing
    text right- and left-stripped, respectively.
    >>> pp(space_normalize(['lead ',
    ...                    ('p', {}, [' Start ', ('i', {} ,[' italic ']),
    ...                              ('b', {}, ['bold ']), ' end ']),
    ... ' trail. ']))
    ['lead',
     ('p', {}, ['Start ', ('i', {}, ['italic ']), ('b', {}, ['bold ']), 'end']),
     'trail. ']

    Footnotes are special cased: only their inner text is stripped, the
    surrounding whitespace is assumed to be significant.
    >>> pp(space_normalize([('p', {}, ['A footnote  ',
    ... ('.footnote', {}, [' w/ spaces! ']), ' -- exciting!'])]))
    [('p',
      {},
      ['A footnote ', ('.footnote', {}, ['w/ spaces!']), ' -- exciting!'])]
    """


    return _space_normalize(es)[0]

# any changes to this regexp need to be reflected in
# `zotero.rb` and `zotero.js` as well
ZOTERO_ITEM_URL_REX = re.compile(
    r'bib:|https?://zotero\.org/(users|groups)/([0-9]+)/items/([A-Z0-9]+)$')
REF_KEY_REX = re.compile(
    r'^(\s*)(\[)?([\w-]+)(?:[:](author|year|title)\b)?(.*?)\]?(\s*)$')

def cite(key, post=None, textual=False, field=None):
    assert field in (None, 'author', 'year', 'title')
    # FIXME(alexander): think about how multi-arg commands should really work
    body = [key] if not (post and post.strip()) else [key, post]
    if not field:
        cmd = 'autocite' if not textual else 'textcite'
    else:
        cmd = 'cite' + (field or '') + ('' if textual else 'p')
    return mkcmd(cmd, body)



def parse_cites(parsed_body, bib_entries, collect_cite): # pylint: disable=R0914
    ZURL = Var('ZURL', ZOTERO_ITEM_URL_REX.match)
    ZBODY = Var('ZBODY', lambda s: REF_KEY_REX.match(plaintextify(s)))
    ans = []
    coalesce_strings = False

    for e in parsed_body:
        if isinstance(e, basestring):
            ans.append(e)
        elif e == ('a', {'href': ZURL}, ZBODY):
            link_text = ZBODY.match.group(0).strip()
            # sp1 and sp2 are potential leading and trailing spaces which we
            # tolerate and move out of the link
            sp1, paren, key, field, post, sp2 = ZBODY.match.groups()
            if bool(paren) != link_text.endswith(']'):
                ans.append(mkerr([e],
                                 'malformed citation, unmatched %s' %  (
                                     '[]'[not paren])))
                continue
            zotero_id = 'http:' + ZURL.match.group(0).split(':', 1)[1]
            collect_cite(key)
            fields = bib_entries[key].fields if key in bib_entries else {}
            # XXX(alexander): cleanse_post_citation kinda takes rich-text, we
            # only do plaintext for now
            post_text, = cleanse_post_citation([post])
            if 'zoteroid' not in fields or fields.get('zoteroid') == zotero_id:
                if sp1:
                    ans.append(sp1)
                    coalesce_strings = True
                ans.append(cite(key, post_text, textual=not paren, field=field))
                if sp2:
                    ans.append(sp2)
                    coalesce_strings = True
            else:
                ans.append(mkerr([e], 'bad citation key'))
        else:
            ans.append(mkel(e[0], e[1],
                            parse_cites(e[2], bib_entries, collect_cite)))
    if coalesce_strings:
        i = 1
        while i < len(ans):
            if (isinstance(ans[i], basestring) and
                    isinstance(ans[i-1], basestring)):
                ans[i-1:i+1] = [ans[i-1] + ans[i]]
            i += 1
    return ans

def underlines_to_commands(parsed_body, lstrip=False): # pylint: disable=R0912
    CATTRS, CBODY = map(
        Var, 'CATTRS, CBODY'.split(', '))
    reparsed = []
    appendpoint = reparsed
    for i, e in enumerate(parsed_body):
        if e == ('u', CATTRS, CBODY):
            assert CATTRS.val == {}
            assert len(CBODY.val) == 1
            # underlines can hide invisible whitespace
            # FIXME(alexander): should make sure this is plain text
            # bogus underlined footnoterefs can e.g. mess this up
            cmd = CBODY.val[0].strip()
            if cmd.endswith(':'): # take args
                reparsed.append(
                    mkcmd(cmd[:-1].lower(),
                          underlines_to_commands(parsed_body[i+1:], True)))
                return reparsed
            elif cmd[:1] == cmd[-1:] == '$':
                reparsed.append(mkcmd('tex', [r'\(%s\)' % cmd[1:-1]]))
            elif cmd[:1] == '\\':
                # FIXME(alexander): this should probably be parsed
                reparsed.append(mkcmd('tex', [cmd]))
            elif cmd[:1] == '<' and cmd[-1] == '>':
                # FIXME(alexander):
                reparsed.extend(tidy(parse_chunk(cmd)))
                mkerr([cmd], 'Underlined tags must be well-formed xml')
            # Transform (invisibly, in GDocs) underlined whitespace to plain
            # whitespace. This should not break up underlined runs of text,
            # because at this point we should already have coalesced those.
            elif not cmd:
                if CATTRS.val:
                    log.warn('Ignoring bogus attributes in `<u> </u>`: %r',
                             CATTRS.val)
                cbody, = CBODY.val
                reparsed.append(cbody)
            else:
                assert cmd
                reparsed.append(mklit(cmd.lower()))
                lstrip = False
        else:
            if isinstance(e, basestring):
                if lstrip:
                    e = e.lstrip()
                if e:
                    appendpoint.append(e)
            else:
                appendpoint.append(mkel(e[0], e[1],
                                        underlines_to_commands(e[2], lstrip)))
            lstrip = False
    return reparsed


CAPTION_AFTER_HEADING = u'''
The caption "{}" follows a heading ("{}"), but should follow a figure or table.
Maybe you forgot to insert a newline between heading and image?
'''
CAPTION_AFTER_NON_FLOAT = u'''
The caption "{}" is not preceded by a table or figure.
Maybe you forgot to insert a newline between caption and figure or table?
'''

def captionize(body):
    CBODY, TAG, PATTRS, FATTRS, FBODY = map(
        Var, 'CBODY, TAG, PATTRS, FATTRS, FBODY'.split(', '))
    ans = []
    for e1, e2 in window(body, 2):
        if e2 in (varcmd('caption', CBODY),
                  ('p', PATTRS,
                   [varcmd('caption', CBODY)])):
            #XXX(alexander): the right way would probably be to normalize
            # justify/left away before we get here.
            e1_is_figure = ((e1 == ('p', PATTRS, [(TAG, FATTRS, FBODY)]) and
                             PATTRS.val in ({}, {'class': ['justify']},
                                            {'class': ['left']})
                             or e1 == (TAG, FATTRS, FBODY))
                            and TAG.val in ('table', 'figure'))
            if not e1_is_figure:
                if TAG.match and TAG.val in H_TAGS:
                    docproblem(CAPTION_AFTER_HEADING,
                               plaintextify(CBODY.val),
                               plaintextify(FBODY.val))
                else:
                    docproblem(CAPTION_AFTER_NON_FLOAT,
                               plaintextify(CBODY.val))
                continue
            if PATTRS.match and PATTRS.val:
                log.warn(
                    'Unexpected attrs in paragraph wrapping the caption: %r',
                    PATTRS.val)
            ans[-1] = (TAG.val, FATTRS.val,
                       [('figcaption' if TAG.val == 'figure' else 'caption',
                         {},
                         CBODY.val)] + captionize(FBODY.val))
        elif e2 == (TAG, FATTRS, FBODY):
            ans.append(mkel(TAG.val, FATTRS.val, captionize(FBODY.val)))
        else:
            ans.append(e2)
    return ans

def unwrap_figures(body):
    # XXX: this currently only operates at the toplevel, both looking for
    # paragraphs and also looking for block figures in paragraphs. Strictly
    # speaking we should probably descend for both. As an additional hack, we
    # descend, up to the the <td> level, into tables.
    FATTRS, PATTRS, FBODY = map(
        Var, 'FATTRS, PATTRS, FBODY'.split(', '))
    BLOCK_STYLE_ATTR = Var('BLOCK_STYLE_ATTR',
                           lambda a: a['style']['display'] == 'block')
    BLOCK_FIG = ('figure', BLOCK_STYLE_ATTR, FBODY)
    PBODY_WITH_BLOCKFIG = Var('PBODY_WITH_BLOCKFIG',
                              list.__contains__, BLOCK_FIG)
    for elem in body:
        if elem and elem[0] in ('table', 'tr', 'td', 'blockquote'):
            yield mkel(elem[0], elem[1], list(unwrap_figures(elem[-1])))
        elif elem in (('p', {}, [('figure', FATTRS, FBODY)]),
                      ('figure', FATTRS, FBODY)):
            # override style of standalone figures
            new_fattrs = copy.deepcopy(FATTRS.val)
            new_fattrs['style']['display'] = 'block'
            yield mkel('figure', new_fattrs, FBODY.val)
        # Split a <p> that contains a block figure into
        # two paragraphs separated by a figure.
        # This case can only arise due to the
        # large inline image heuristic; if the paragraph
        # has an id attribute (shouldn't happen yet),
        # we put it into the first half of the split. We throw away
        # empty <p>s.
        elif elem == ('p', PATTRS, Seq[PBODY_WITH_BLOCKFIG:]):
            body = PBODY_WITH_BLOCKFIG.val
            i_fig = body.index(BLOCK_FIG)
            if body[:i_fig]:
                yield mkel('p', PATTRS.val, body[:i_fig])
                cloned_attrs = dict((k, v) for (k, v) in PATTRS.val.items()
                                    if k != 'id')
            else:
                cloned_attrs = PATTRS.val
            yield body[i_fig]
            if cloned_attrs or body[i_fig+1:]:
                yield ('p', cloned_attrs, body[i_fig+1:])
        else:
            yield elem

def blank_flat_body(body):
    return tidy(whack(INLINE_TAG.__contains__, body)) == Seq[:](
        lambda ss: all(isinstance(s, basestring) and not s.strip()
                       for s in ss))


def _pop_title_and_subtitle(body, head):
    """Pops (sub)titles from `body`' and stuff them into ``head``."""
    _, BODY, REST = map(Var, '_, BODY, REST'.split(', '))
    for tag, alt_h in [('title', 'h1'), ('subtitle', 'h2')]:
        if body in (Seq[(tag, {}, Seq[BODY:]), REST:],
                    Seq[(alt_h, {'class': tag}, Seq[BODY:]), REST:]):
            # XXX(alexander): plaintextification of (sub)titles
            title_str = space_normalize(plaintextify(BODY.val))
            if title_str:
                head[tag] = title_str
            del body[0]
        # skip empty paragraphs between title and subtitle and subtitle and meta
        while body and body[0] in [
                Var('_', lambda x: isinstance(x, basestring) and blank(x)),
                ('p', _, Seq(blank_flat_body)[:])]:
            log.warn('Killing blank gunk before metadata')
            del body[0]

def _pop_dl_meta(body, head):
    """Pops ``<dl>`` encoded metadata from `body` and stuffs it into `head`."""
    DL_BODY = Var('DL_BODY')
    if body == Seq[('dl', {'id': 'document-properties'}, DL_BODY), :]:
        del body[0]
        dl_body = space_normalize(DL_BODY.val)
        DD_BODY, ATTRS = map(Var, 'DD_BODY, ATTRS'.split(', '))
        DT = ('dt', Var('_'), Var('_'))
        DD = ('dd', ATTRS, DD_BODY)
        for dt_dd in zip(dl_body[::2], dl_body[1::2]):
            assert (DT, DD) == dt_dd
            c, = ATTRS.val['class']
            head[c] = ATTRS.val.get('data-value', plaintextify(DD_BODY.val))

def _pop_underlined_meta(body, head, transclusions):
    NAME, VALUES, ATTRS, LITERAL, SRC, _ = map(
        Var, 'NAME, VALUES, ATTRS, LITERAL, SRC, _'.split(', '))
    while body and body[0] in (
            ('p', _, [varcmd(NAME, Seq[VALUES:])]),
            # XXX(alexander): this is a pretty special-case hack to deal with
            # left-over anchors resulting from re-editing a heading as a
            # document-property
            ('p', _, [('a', {'name': _}, []), varcmd(NAME, Seq[VALUES:])])):
        if VALUES.val == [varlit(LITERAL)]:
            head[NAME.val] = literal.parse_literal(LITERAL.val)
        elif VALUES.val == [varel('figure',
                                  ATTRS,
                                  [varel('img', {'src': SRC}, [])])]:
            head[NAME.val] = literal.Image(
                data=transclusions.get_data(SRC.val),
                mimetype=transclusions.get_mimetype(SRC.val),
                style=ATTRS.val['style'])
        else:
            head[NAME.val] = tidy(VALUES.val)
        del body[0]

def extract_meta(parsed_body, transclusions): # pylint: disable=R0914
    parsed_body = parsed_body[:]
    head = OrderedDict()
    _pop_title_and_subtitle(parsed_body, head)
    _pop_dl_meta(parsed_body, head)
    _pop_underlined_meta(parsed_body, head, transclusions)
    return head, parsed_body

MISSING_BIBLIOGRAPHY = '''Your document contains citations like {}, \
but you did not include a bibliography'''
def postprocess(raw_body, transclusions, bibliography=None, asides=False):
    citations = set()
    # kill comments early, because they can mess things up
    # (e.g. by splitting commands or citations)
    # FIXME(alexander): comments should probably be out-of-band
    if not asides:
        raw_body = whack('aside'.__eq__, raw_body, kill_body=True)

    # FIXME(alexander): investigate the performance impact of this final tidy
    # -- it's needed for tidying up stuff that happened after commandification
    # (currently that only affects blockquotes)
    raw_parsed_body = tidy(
        space_normalize(list(unwrap_figures(captionize(
            underlines_to_commands(
                parse_cites(coalesce(raw_body),
                            bib_entries=getattr(bibliography, 'entries', {}),
                            collect_cite=citations.add)))))))
    unaugmented_head, body = extract_meta(raw_parsed_body, transclusions)
    if citations:
        if 'bibliography' not in unaugmented_head:
            docproblem(MISSING_BIBLIOGRAPHY, sorted(citations)[0])
    return unaugmented_head, body
