#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
#pylint: disable=C0103
r"""A whitespace normalizing html5 parser.

XXX(alexander): what html and python consider whitespace is not quite the
same; python includes `\v`, html does not -- this is mostly ignored here, as I
think it's unlikely to matter in practice and would complicate the code a bit.
"""


from collections import OrderedDict
import logging as log
import regex as re

import cssutils
import cssutils.css

from html5lib import sanitizer
import html5lib
from lxml import etree
import lxml.html
from lxml.html.clean import Cleaner
from lxml.html.defs import safe_attrs
from bs4 import UnicodeDammit

from converter.ezmatch import Var
from converter.internal import COLOR_TYPES, mkcmd, mkel, ALLOWED_TAGS
from converter.preprocess import maybe_anchorize_id

FIGURE_PROPS = ('display', 'width')

ALIGNMENTS = ('left', 'center', 'right', 'justify')

# FIXME(alexander): monkey patch html5lib to allow through data urls
import lxml.html.clean
lxml.html.clean._javascript_scheme_re = re.compile( # pylint: disable=W0212
    r'\s*(?:javascript|jscript|livescript|vbscript|about|mocha):', re.I)

EXTRA_ATTRS = {'style', 'data-value', 'data-continue-list'}

def _clean_inplace(xml):
    # don't clean style attrs; they carry semantic info in some cases
    Cleaner(style=False,
            page_structure=False,
            safe_attrs=safe_attrs | EXTRA_ATTRS)(xml)
    return xml

def parse_html(s):
    """Parse a whole html doc `s` to an lxml etree.

    See `parse_html_frag` docstring as well.
    """
    # lxml.html chockes on whitespace or empty s
    s = s.strip() or '<body></body>'
    dammit = UnicodeDammit(s, is_html=True)
    parser = lxml.html.HTMLParser(encoding=dammit.original_encoding)
    xml = lxml.html.document_fromstring(s, parser=parser)
    return _clean_inplace(xml)

class Sanitizer(sanitizer.HTMLSanitizer): # pylint: disable=R0904
    # allow data urls, disallow other cruft
    allowed_protocols = ['http', 'https', 'ftp', 'sftp', 'urn', 'data']

def parse_html_frag(s):
    """Parse a html fragment `s` to an lxml etree.

    Will sanitize the html. Note that this behaves (for many use cases) pretty
    irritatingly: invalid tags are just converted to plain text (rather than
    stripped). This includes stuff like ``<body>`` meaning a valid html
    document as `s` is converted into some monstrosity with everything down to
    and including the original body transformed into some horrible
    entity-encoded mess that forms the content of the new, but not improved,
    body. That also implies there is no sane way to get at the actual original
    body content that I cans ee.

    Unfortunately from what I can see, that appears just a reflection of the
    semi-official html5lib sanitizer we use -- but maybe there is a better way
    to go about this. For this reason, and also because of the way <spans>
    with block elements (like ``<p>``s) inside are handled, we have
    `parse_html` as well, which uses a different html lib and is intended to
    parse whole input documents (as opposed to frags from document properties
    and inline html etc.).
    """
    if not isinstance(s, unicode) and s != '':
        # I don't think we have much hope of detecting the encoding from
        # arbitrary html fragments
        log.warn("Non-unicode input given to parse_html_frag: %r", s)
    parser = html5lib.HTMLParser(
        tree=html5lib.treebuilders.getTreeBuilder("lxml"),
        namespaceHTMLElements=False,
        tokenizer=Sanitizer)
    xml = parser.parse(s)
    return xml


def space_normalize(s):
    if not s:
        return ''
    # http://developers.whatwg.org/common-microsyntaxes.html#space-character
    # note that this does not include unicode spaces or '\v'
    return re.sub(r'[\n\r\t ]+', ' ', s)

def color_normalize(color_string, strip_alpha=True):
    """Normalize CSS color to hex or rgba."""
    color = cssutils.css.ColorValue(color_string)
    if color.alpha == 1.0 or strip_alpha:
        return "#%02x%02x%02x" % (color.red, color.green, color.blue)
    else:
        return "rgba(%d,%d,%d,%f)" % (color.red, color.green, color.blue,
                                      color.alpha)

def style_normalize(tag, style):
    props = (prop for prop in cssutils.parseStyle(style)
             if prop.wellformed)
    if tag == 'figure':
        ans = OrderedDict(sorted([(str(prop.name), str(prop.value))
                                  for prop in props
                                  if prop.name in FIGURE_PROPS],
                                 key=lambda (k, v): FIGURE_PROPS.index(k)))
        if 'display' not in ans:
            ans['display'] = 'block'
    elif tag in ('img', 'col'):
        ans = OrderedDict((str(prop.name), str(prop.value))
                          for prop in props
                          if prop.name == 'width')
    else:
        # only allow color and background-color; normalize them
        ans = OrderedDict([(str(prop.name), color_normalize(prop.value))
                           for prop in props if prop.name in COLOR_TYPES])
    return ans


def _get_width(attrs, default_width):
    return attrs.get('style', {}).get('width', default_width)

def _cleanup_fig(attrs, body):
    if body:
        if isinstance(body[-1], basestring) and not body[-1].strip():
            del body[-1]
        if body[-1][:1] == ('figcaption',):
            body[0], body[-1] = body[-1], body[0]
        if _get_width(attrs, None) is None:
            img = body[-1]
            if img[:1] == ('img',):
                width = _get_width(img[1], '100%')
                style = attrs.setdefault('style', OrderedDict())
                if 'display' not in style:
                    style['display'] = 'block'
                style['width'] = width
                img[1].pop('style', {}).pop('width', {})

def _cleanup_classes(tag, attrs):
    classes = []
    for c in attrs['class'].split(' '):
        for class_to_promote, for_tags in [
                ('title', ('h1',)),
                ('subtitle', ('h2',)),
                ('footnote', ('span', 'div', 'aside')),
                ('pagebreak', ('span', 'div')),
                ('tex2jax_process', ('span',))]:
            if c == class_to_promote and tag in for_tags:
                tag = '.' + c if c not in ('title', 'subtitle') else c
                break
        else:
            if tag in ('td', 'th') and c in ALIGNMENTS:
                pass
            else:
                classes.append(c)
    if not classes:
        del attrs['class']
    else:
        attrs['class'] = classes
    return tag

def _cleanup_attrs(tag, attrs):
    for attr in attrs.keys():
        if not (attr in {'style', 'class', 'id'} or
                attr.startswith('data-')):
            if (attr in ('name', 'href') and tag == 'a' or
                attr == 'src' and tag == 'img') or ( # pylint: disable=c0330
                    attr == 'start' and tag in ('ol', 'ul')):
                continue
            elif attr == 'width' and tag == 'col':
                attrs['style'] = 'width:' + attrs['width']
            del attrs[attr]

def _cleanup_style(tag, attrs):
    normalized_style = style_normalize(tag, attrs['style'])
    if normalized_style:
        attrs['style'] = normalized_style
    else:
        del attrs['style']


def _de_data_url(handle_data_url, attrs):
    if handle_data_url and attrs.get('src', '').startswith('data:'):
        attrs['src'] = handle_data_url(attrs['src'])


def _maybe_handle_footnote(tag, attrs, body, footnote_state):
    classes = attrs.get('class', [])
    if tag == 'a' and 'noteref' in classes:
        href = attrs['href']
        if href.startswith('#'):
            # pylint: disable=W0622
            id = href[1:]
            footnote_state[id] = body
            return [mkel('.footnote', {}, body)]
        else:
            # XXX(ash): make user-visible
            log.warn("Found a footnote reference but didn't understand its "
                     "href (%s), so skipping it.", href)
            return []
    if tag == 'aside' and 'endnote' in classes:
        print attrs, body
        id_ = attrs['id']
        old_body = footnote_state.pop(id_, None)
        if old_body is None:
            # XXX(ash): make user-visible
            log.warn("Found a footnote body but its id (%s) doesn't match any "
                     "footnote reference seen previously, so skipping it.", id_)
        else:
            # overwrite the body of the anchor we saved earlier
            old_body[:] = body
        return []
    return None


def _parse_body(xml, handle_data_url, parent_tag, footnote_state):
    # pylint: disable=R0912,R0914
    if parent_tag == 'pre':
        return [etree.tostring(xml, method="text")]
    ans = []
    xml = list(xml)
    for e in xml:
        tag = e.tag
        text = e.text or ''
        tail = e.tail or ''
        body = _parse_body(xml=e,
                           handle_data_url=handle_data_url,
                           parent_tag=tag,
                           footnote_state=footnote_state)
        attrs = dict(e.attrib)
        _cleanup_attrs(tag, attrs)
        if text:
            body = [text] + body
        if 'class' in attrs:
            tag = _cleanup_classes(tag, attrs)
        if 'style' in attrs:
            _cleanup_style(tag, attrs)
        if tag == 'figure':
            # put figcaption in canonical order
            _cleanup_fig(attrs, body)
        elif tag == 'img' and parent_tag != 'figure':
            img_attrs, img_body = attrs, body
            _de_data_url(handle_data_url, img_attrs)
            # XXX(alexander): pop the 'margin' class;
            # the display 'inline' covers that
            if 'margin' in img_attrs.get('class', []):
                img_attrs['class'].remove('margin')
                if not img_attrs['class']:
                    del img_attrs['class']
            tag, attrs = 'figure', {'style':
                                    OrderedDict([('display', 'inline')])}
            body = [mkel('img', img_attrs, img_body)]

            _cleanup_fig(attrs, body)
        _de_data_url(handle_data_url, attrs)
        maybe_anchorize_id(tag, attrs, body)
        footnote = _maybe_handle_footnote(tag, attrs, body, footnote_state)
        if footnote is not None:
            ans.extend(footnote)
        elif tag in ALLOWED_TAGS:
            ans.append(mkel(tag, attrs, body))
        elif tag == '.tex2jax_process':
            ans.append(mkcmd('tex', body))
        else:
            log.info('Stripping non-allowed tag %s', tag)
            ans.extend(body)
        if tail:
            ans.append(tail)
    return ans

def _warn_about_unhandled_footnotes(footnote_state):
    for k in footnote_state:
        # XXX(ash): make user-visible
        log.warn("There was a footnote reference to #%s but I didn't see the "
                 "body for it. (Did the body come after the reference?)", k)

def parse_body(xml, handle_data_url, parent_tag=None):
    footnote_state = {}
    outp = _parse_body(xml=xml,
                       handle_data_url=handle_data_url,
                       parent_tag=parent_tag,
                       footnote_state=footnote_state)
    _warn_about_unhandled_footnotes(footnote_state)
    return outp

def parse_chunk(s, handle_data_url=None):
    BODY = Var('BODY')
    parsed = parse_body([parse_html_frag(s).find('body')], handle_data_url)
    assert [('body', {}, BODY)] == parsed, 'No body in %r' % (parsed,)
    return BODY.val

def parse_to_raw_body(infilename, rewritten_input, make_transclusions):
    assert not rewritten_input, "no input file rewriting for .html input"
    transclusions = make_transclusions({})
    infile = (open(infilename, 'rb') if isinstance(infilename, basestring)
              else infilename)
    try:
        s = infile.read()
    finally:
        infile.close()
    html = parse_html(s)
    lang = next(html.iter()).attrib.get('lang', None) #pylint: disable=W0612
    handle_data_url = transclusions.add_data_url
    raw_body = parse_body(html.find('body'), handle_data_url=handle_data_url)
    return raw_body, transclusions, []


def rewrite_input(*_, **__):
    pass
