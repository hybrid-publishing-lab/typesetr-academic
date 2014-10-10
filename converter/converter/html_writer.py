#!/usr/bin/env python
#-*- file-encoding: utf-8 -*-
import cgi
import copy
import regex as re
from collections import OrderedDict

from converter import docerror
from converter.ezmatch import Var
from converter import highlight
from converter.internal import INLINE_TAG, mkel, H_TAGS, add_class
from converter.lang import Lang
from converter.literal import Bibliography, Image, doc_uuid
from converter.unparse import unparse_literal
from converter.citations import CITE_REX
from converter.transclusions import Transclusions
from converter.sectionize import sectionize, unsectionize, make_stable_gensym
from converter.endnotify import endnotify
from converter.dublin import Person

INLINE = INLINE_TAG + ('CMD', 'ERR', 'LIT') # XXX

# http://www.w3.org/TR/html-markup/syntax.html#syntax-elements
VOID_TAGS = frozenset('''area base br col command embed hr img input keygen
                         link meta param source track wbr'''.split())

NOT_INLINE_TEMPLATE = ("\n%(indent)s<%(tag)s%(attrs_str)s>"
                       "%(content_str)s"
                       "\n%(indent)s</%(tag)s>")
COMPACT_NOT_INLINE_TEMPLATE = (
    "\n%(indent)s<%(tag)s%(attrs_str)s>%(content_str)s</%(tag)s>")


def meta_to_html(meta):
    # pylint: disable=R0914
    # FIXME(alexander): this is just a really hacky way to convert the
    # document properties into something vaguely visually plausible in a style
    # independent manner
    head = meta.items()
    lang = head['lang']
    prepend = []
    title = head.pop('title', '')
    # FIXME(alexander): should maybe default to docname?
    # the only style which does currently not have a title
    # is letter, so could use subject there
    if title:
        prepend.append(mkel('h1', {'class': ['title']}, [title]))
    subtitle = head.pop('subtitle', '')
    if subtitle:
        prepend.append(mkel('h2', {'class': ['subtitle']}, [subtitle]))
    dl_body = []
    types_to_omit = (int, Bibliography, Image, Lang)
    #FIXME(alexander): toc-depth should be int,
    #                  and bibliography-preamble must die
    keys_to_omit = ('toc-depth', 'bibliography-preamble')
    for (k, v) in head.iteritems():
        is_default_value = 'supplied' not in meta.d[k]
        if is_default_value:
            continue
        a = {'class': [k]}
        if isinstance(v, types_to_omit) or k in keys_to_omit:
            a['hidden'] = ""
        label = meta.d[k].get('label', k.capitalize())
        dl_body.append(mkel('dt', a, [lang.localize(label)]))
        a = a.copy()
        dd = unparse_literal(v, roundtrip=False)
        roundtrippable = unparse_literal(v)
        if dd != roundtrippable:
            a['data-value'] = roundtrippable
        dl_body.append(mkel('dd', a, [dd if not isinstance(v, bool)
                                      else lang.localize(dd)]))

    if dl_body:
        prepend.append(mkel('dl', {'id': 'document-properties'}, dl_body))

    return lang.code, title, prepend


def _endnotify_html(body):
    section_attrs = {
        'class': ['endnotes'],
    }
    aside_attrs = {
        'class': ['endnote'],
    }
    a_attrs = {
        'class': ['noteref'],
    }
    return endnotify(body, aside_attrs, a_attrs, section_attrs)


def write(out_file, style_template, bibliography, # pylint: disable=R0913,R0914
          meta, parsed_body, transclusions):
    """Generate code that is both valid xml and valid (plain) html5."""
    lang, title, prepend = meta_to_html(meta)
    # TODO: don't discard toc
    uuid = doc_uuid(meta, parsed_body, transclusions)
    sectioned, _ = sectionize(parsed_body, kill_anchors=False,
                              gensym=make_stable_gensym(uuid))
    endnotified = _endnotify_html(sectioned)
    # We prefer our HTML not to have nested sections, so we strip them out.
    unsectioned = unsectionize(endnotified)  # XXX(ash): this is not cool.
    body_str = write_body(
        parsed_body=prepend + unsectioned,
        bibliography=bibliography,
        indent='',
        transclusions=transclusions,
        h_shift=style_template.h_shift)

    if bibliography:
        parsed_bibliography = _append_bibliography(bibliography)
        if parsed_bibliography:
            body_str += write_body(parsed_bibliography)

    print >> out_file, style_template.html_template(
        inline=not transclusions.out_dir,
        body=body_str,
        lang=lang,
        title=title)



# pylint: enable=C0301
def encode_attrs(attrs, transclusions, epub_clean):
    if not attrs:
        return ""
    def encode_attr((k, v)):
        if k in ('src', 'href'):
            val, embedded = transclusions.handle_href(v, never_embed=epub_clean)
            # generally we escape urls, just to be on the safe side and to
            # generate valid xml (which is useful for tooling). However data
            # urls don't need escaping
            if embedded:
                return '%s="%s"' % (k, val)
        elif k in 'class':
            val = " ".join(v)
        elif k in 'style':
            val = ";".join(map(u"%s:%s".__mod__, v.iteritems()))
        else:
            val = v
        return k + '="' + cgi.escape(val) + '"'

    return " " + " ".join(map(encode_attr,
                              sorted(attrs.items(), key=lambda x: x[0])))

def _space_kludge(s):
    """Pre-strip and get rid of trailing spaces in all lines."""
    # XXX: not strictly semantics preserving for <pre> or <textarea>;
    # could be fixed at pre generation by something like
    #    content_str.replace(' \n', '&#32;\n')
    # but then we'd have to look out for <script>s in <pre>s
    return "\n".join(line.rstrip() for line in s.strip().split('\n'))

def write_body(parsed_body, bibliography=None, # pylint: disable=R0913
               transclusions=Transclusions({}), indent='', h_shift=0,
               epub_clean=False):
    #strip leading newline to make pretty-printing fragments easier
    return _space_kludge(handle_fragments(
        parsed_body, indent, transclusions, h_shift, epub_clean,
        bibliography))

def handle_fragments(parsed_body, indent, # pylint: disable=R0913
                     transclusions, h_shift, epub_clean, bibliography):
    return "".join([handle_fragment(frag,
                                    indent=indent,
                                    transclusions=transclusions,
                                    h_shift=h_shift,
                                    epub_clean=epub_clean,
                                    bibliography=bibliography)
                    for frag in parsed_body])

CDATA_TEMPLATE = '''\
/*<![CDATA[*/
%s
/*]]>*/'''

def maybe_cdatafy(s):
    needs_escaping = '<' in s or '&' in s
    if not needs_escaping:
        return s
    return CDATA_TEMPLATE % s.replace(']]>', r']]\>')

def _indent(s, indent):
    return ''.join((indent + line) if line != '\n' else line
                   for line in s.splitlines(True))

def _propagate_alignment(content, cols):
    trs = [el for el in content if el[0] == 'tr']
    for _, _, tds in trs:
        assert len(tds) == len(cols), \
            "Table row has not enough cells: %s" % tds
        for cid, col in enumerate(cols):
            if 'class' in col[1]:
                attrs = tds[cid][1]
                # FIXME ugly hack
                attrs.update(add_class(attrs, *col[1]['class']))

ALPHA_NUMERIC_REX = re.compile(r'[^0-9a-zA-Z]+')
def _bibliography_anchor(key):
    return ALPHA_NUMERIC_REX.sub('-', key)

CITE_P_REX = re.compile(r'cite(author|year|title)(p)?')
def _format_citation(command, key, bibliography):
    text = ''
    entry = bibliography.entries[key]

    if len(entry.persons['author']) == 0:
        author = 'Anon'
    else:
        author = ' '.join(entry.persons['author'][0].last())
        if len(entry.persons['author']) > 1:
            author += ' et al.'

    if command == "autocite":
        text = "(%s, %s)" % (author, entry.fields['year'])
    elif command == "textcite":
        text = "%s (%s)" % (author, entry.fields['year'])
    else:
        matches = CITE_P_REX.search(command)
        parenthesis = matches.group(2) == 'p'
        if parenthesis:
            text = '('
        text += {
            'author': author,
            'year': entry.fields['year'],
            'title': entry.fields['title']
        }[matches.group(1)]
        if parenthesis:
            text += ')'

    return '<cite class="citation"><a href="#%s">%s</a></cite>' % (
        _bibliography_anchor(key), text)

def _append_bibliography(bibliography): # pylint: disable=R0912,R0914
    def intersperse(delimiter, iterable):
        it = iter(iterable)
        yield next(it)
        for x in it:
            yield delimiter
            yield x

    def item_attributes(itemprop=None, itemtype=None, itemscope=None):
        attributes = dict()

        if itemprop:
            attributes['itemprop'] = itemprop

        # For validation purposes, itemtype and itemscope must be defined
        # at the same time
        if itemtype:
            assert itemscope, "itemtype must not be specified " +\
                              "on elements without itemscope"
            attributes['itemtype'] = "http://schema.org/" + itemtype
            attributes['itemscope'] = itemscope

        return attributes

    def gen_name(person):
        parsed_person = Person(person)
        name = []

        parts = [
            ('last', '.last-name', 'familyName'),
            ('first', '.first-name', 'givenName'),
            ('particle', '.lineage', 'lineage'),
        ]
        for part_name, css_class, itemprop in parts:
            part = parsed_person.parts.get(part_name)
            if part:
                name.append(mkel(css_class, item_attributes(itemprop), [part]))

        return list(intersperse(', ', name))

    def gen_field_maker(entry, field_name, attrs, # pylint: disable=R0913,R0914
                        css_class='', element='', format_string='%s'):
        """
            Generic Field Maker
        """
        def gen_field():
            if field_name in entry.fields:
                yield mkel('.'.join([element, css_class]), attrs,
                           [format_string % entry.fields[field_name]])
        return gen_field()

    def gen_authors(entry):
        try:
            authors = [mkel('.author',
                            item_attributes('author', 'Person', 'itemscope'),
                            gen_name(a)) for a in entry.persons['author']]
        except KeyError:
            authors = [mkel('.author', {}, ['Anon'])]

        separator = mkel('.author-separator', {}, ['; '])
        yield mkel('span.authors', {}, list(intersperse(separator, authors)))

    def gen_journal(entry):
        journal = []
        try:
            journal.append(mkel('.journal-title',
                                item_attributes('isPartOf',
                                                'Periodical', 'itemscope'),
                                [entry.fields['journal']]))
        except KeyError:
            pass

        try:
            journal.append(mkel('.volume',
                                item_attributes('volumeNumber'),
                                [entry.fields['volume']]))
            journal.append(
                mkel('.number',
                     item_attributes('issueNumber'),
                     ['(', entry.fields['number'], ')']))
        except KeyError:
            pass

        if journal:
            yield mkel('.journal',
                       item_attributes('isPartOf',
                                       'PublicationVolume', 'itemscope'),
                       list(intersperse(' ', journal)))

    def gen_year(entry):
        return gen_field_maker(entry, 'year',
                               item_attributes('datePublished'), 'year')

    def gen_title(entry):
        css_class = 'title'
        if entry.type == 'book' or entry.type == 'inbook':
            css_class += ' book'

        return gen_field_maker(entry, 'title',
                               item_attributes('name'), css_class)

    def gen_page(entry):
        return gen_field_maker(entry, 'pages',
                               item_attributes('page'), 'pages')

    def gen_publisher(entry):
        return gen_field_maker(entry, 'publisher', item_attributes('publisher'),
                               'publisher')

    def gen_chapter(entry):
        return gen_field_maker(entry, 'chapter',
                               item_attributes('chapterNumber'), 'chapter',
                               format_string="chap. %s")

    def gen_booktitle(entry):
        return gen_field_maker(entry, 'booktitle',
                               item_attributes('publicationTitle'), 'booktitle',
                               format_string="In %s")

    def gen_url(entry):
        attr = item_attributes('url')
        try:
            attr['href'] = entry.fields['url']
            yield mkel('a.url', attr, [entry.fields['url']])
        except KeyError:
            pass

    def gen_school(entry):
        return gen_field_maker(entry, 'school', item_attributes('school'),
                               'school')

    def gen_text(text):
        yield text

    def gen_entry(entry, key):
        generators = {
            'article': [gen_authors, gen_year, gen_title,
                        gen_journal, gen_page],
            'book': [gen_authors, gen_year, gen_title, gen_publisher],
            'proceedings': [gen_authors, gen_year, gen_title, gen_publisher],
            'inbook': [gen_authors, gen_year, gen_title, gen_title,
                       gen_publisher, gen_chapter, gen_page],
            'phdthesis': [gen_authors, gen_year, gen_title,
                          gen_text('PhD diss.'), gen_school],
            'inproceedings': [gen_authors, gen_year, gen_title, gen_booktitle,
                              gen_publisher, gen_page],
            'mastersthesis': [gen_authors, gen_year, gen_title,
                              gen_text('Master diss.'), gen_school],
            'misc': [gen_authors, gen_year, gen_title, gen_url]
        }.get(entry.type, 'misc')

        li_fields = [field for gen in generators for field in gen(entry)]
        li_fields = list(intersperse('. ', li_fields))
        li_fields.append('.')
        li_type = {
            'article': 'ScholarlyArticle',
            'book': 'Book',
            'proceedings': 'ConferenceProceedings',
            'inbook': 'BookChapter',
            'phdthesis': 'PhdThesis',
            'inproceedings': 'ConferenceProceedings',
            'mastersthesis': 'MasterThesis',
            'misc' : 'Misc'
        }.get(entry.type, 'misc')

        li_attributes = item_attributes('citation', li_type, 'itemscope')
        li_attributes['id'] = _bibliography_anchor(key)

        return mkel('li.ref', li_attributes, li_fields)

    # Nothing was cited
    if not len(bibliography.cited):
        return None
    # Filter entries by cited
    entries = {key: bibliography.entries[key] for key in bibliography.cited}
    ol = []

    # Sort by key
    entries_sorted = sorted(entries)
    for key in entries_sorted:
        ol.append(gen_entry(entries[key], key))

    return [mkel('ol.ref',
                 item_attributes(None, 'Bibliography', 'itemscope'), ol)]


def handle_fragment(fragment, indent,
                    transclusions, h_shift, epub_clean, bibliography):
    # pylint: disable=R0911,R0914,R0912,R0913,R0915
    # FIXME(alexander): clean this up a bit, and get rid of pylint muffles
    if isinstance(fragment, basestring):
        return cgi.escape(fragment)

    (tag, attrs, content) = fragment
    if tag in ['script', 'style'] and content:
        content_str, = content
        return NOT_INLINE_TEMPLATE % dict(
            indent=indent,
            tag=tag,
            attrs_str=encode_attrs(attrs, transclusions, epub_clean),
            content_str=_indent(
                '\n' + maybe_cdatafy(_indent(content_str.strip('\n'), ' ')),
                indent))
    if tag == 'pre':
        return '\n' + highlight.as_html(fragment)

    # special case figures and tables
    if tag == 'figure':
        style = attrs['style'].copy()
        width = style.pop('width', '100%')
        attrs = dict(attrs.items(), style=style)
        # FIXME(alexander): dirty hacks to fixup caption & width
        img = content[-1]
        assert img[0] == 'img'
        img[1].setdefault('style', OrderedDict())['width'] = width
        # put figcaption towards end
        if content[0][0] == 'figcaption':
            content[0], content[-1] = content[-1], content[0]
        if style['display'] == 'inline':
            ATTRS = Var('ATTRS') # pylint: disable=C0103
            assert content[:1] == [('img', ATTRS, [])], \
                "figure does not begin with an img"
            attrs = add_class(ATTRS.val, 'margin')
            # peel of the figure tag for inlined stuff
            # as a hack to make epub/html validate
            # (figures can't occur in all contexts imgs can)
            return handle_fragments([('img', attrs, [])],
                                    bibliography=bibliography,
                                    indent=indent,
                                    transclusions=transclusions,
                                    h_shift=h_shift,
                                    epub_clean=epub_clean)
    elif tag == 'table':
        colgroups = [el for el in content if el[0] == 'colgroup']
        COLS = Var("COLS") # pylint: disable=C0103
        assert colgroups == [('colgroup', {}, COLS)], \
                "Expected single colgroup in table %s" % content
        # FIXME(alexander): this deepcopy is a lazy hack so we can mutate away
        # imperatively propagate table cell alignment down
        # this is a pretty horrible hack and would blow
        # up nastily if there is attribute aliasing,
        # but deepcopying should kinda make it work
        content = copy.deepcopy(content)
        _propagate_alignment(content, COLS.val)

    elif tag == 'col':
        if not epub_clean:
            attrs = attrs.copy()
            attrs['width'] = attrs['style']['width']
            del attrs['style']
        # cull
        ## return handle_fragments(content, indent)
    # FIXME(alexander): might make more sense to filter (or h-ify) these out
    # elsewhere, but for now this seems not unreasonable
    elif tag == 'title':
        tag = 'h1'
        attrs = add_class(attrs, 'title')
    elif tag == 'subtitle':
        tag = 'h2'
        attrs = add_class(attrs, 'subtitle')
    elif tag in ('CMD', 'LIT'):
        bad_command = None
        cmd_type, = attrs['class']
        # FIXME(alexander): convert tex to html for non-math;
        # convert tex math to MML for epub
        if cmd_type in ('$', 'tex'):
            tex, = content
            if cmd_type == '$':
                tex = r'\(%s\)' % tex
            return '<span class="tex2jax_process">%s</span>' % cgi.escape(tex)
        elif CITE_REX.match(cmd_type):
            if bibliography:
                bibliography.cited.add(content[0])
                # post = ('[%s]' % content[1] if len(content) > 1 and content[1]
                #         else '')
                # Post is ignored for the moment
                return _format_citation(cmd_type, content[0], bibliography)
            else:
                docerror.docproblem(
                    'Citation exists, but bibliography is missing')
        else:
            bad_command = cmd_type + (':' if content else '')
            docerror.docproblem('Unknown command type:%s' % cmd_type)
    elif epub_clean:
        if tag == 'a' and 'name' in attrs:
            assert len(attrs) == 1
            attrs = {'id': attrs['name']}
        elif tag == 'img':
            attrs = {k: attrs[k] for k in attrs if k not in ('width', 'height')}

    # FIXME(alexander): support continued-list properly in html, by keeping
    # track of numbers of items per list-id and translating it to start

    if tag in H_TAGS:
        if h_shift:
            tag = 'h%d' % min(len(H_TAGS), max(1, int(tag[1]) + h_shift))


    # generic [tagname].class tags
    if '.' in tag:
        if tag == '.pagebreak':
            tag = 'div.pagebreak' # for whitespace sanitization
        tagname, classname = tag.split('.', 1)
        tag = tagname or 'span'
        attrs = add_class(attrs, classname)

    if tag == 'CMD' and bad_command:
        tag = 'span'
        attrs = {'class': ['bad-command']}
        content = [('u', {}, [bad_command])] +  content
    elif tag == 'ERR':
        tag = 'span'
        attrs = {'class': ['err'], 'title': attrs['info'][0]}

    content_str = handle_fragments(content,
                                   indent='  ' + indent,
                                   transclusions=transclusions,
                                   h_shift=h_shift,
                                   epub_clean=epub_clean,
                                   bibliography=bibliography)
    if tag in VOID_TAGS:
        assert not content
        template = "<%(tag)s%(attrs_str)s/>"
    elif tag in INLINE:
        template = "<%(tag)s%(attrs_str)s>%(content_str)s</%(tag)s>"
    elif '\n' in content_str:
        template = NOT_INLINE_TEMPLATE
    else:
        template = COMPACT_NOT_INLINE_TEMPLATE

    # FIXME(alexander): disgusting hack; fix this properly and
    # use a set representation to start with!
    classes = attrs.get('class')
    if classes:
        attrs = attrs.copy()
        attrs['class'] = sorted(set(classes))

    return template % dict(
        indent=indent,
        tag=tag,
        attrs_str=encode_attrs(attrs, transclusions, epub_clean),
        content_str=content_str)
