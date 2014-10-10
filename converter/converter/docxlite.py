# -*- encoding: utf-8 -*-
from collections import namedtuple, OrderedDict
from cStringIO import StringIO
from zipfile import ZipFile

from converter.xml_namespaces import docx_ns as ns
from converter.xmltools import to_etree, tup2etree, etree2s, etree2tup
from converter.mimetype import extension as guess_extension

PREL_URI = 'http://schemas.openxmlformats.org/package/2006/relationships'
REL_URI = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
VIDEO_REL_URI = REL_URI + '/video'
IMAGE_REL_URI = REL_URI + '/image'

# FIXME(ash): we don't know where this comes from atm
MAGIC_WORD = 'word'


def val(e, child_tag, attrib=ns.w('val')):
    if e is None:
        return None

    for child in e.iter(child_tag):
        return child.attrib.get(attrib)
    return None


Part = namedtuple('Part', 'e rels path rels_path')


def parse_rels(e):
    return {rel.attrib['Id']: rel for rel in e}


def get_rels_path(path):
    parts = path.rsplit('/', 1)
    return '%s/_rels/%s.rels' % tuple(parts)


def get_part(z, path):
    rels_path = get_rels_path(path)

    def get(p, t, d):
        contents = z.get(p)
        if contents is None:
            return d
        else:
            return t(to_etree(contents))

    return Part(e=get(path, lambda x: x, None),
                rels=get(rels_path, parse_rels, {}),
                path=path,
                rels_path=rels_path)


def rels2s(rels):
    tups = [etree2tup(rel)[0] for rel in rels.values()]
    e = tup2etree(('Relationships', {}, tups), nsmap={None: PREL_URI})
    ans = etree2s(e, decl=True)
    return ans


NumStyle = namedtuple('NumStyle', 'numFmt lvlText')


def fresh_name(existing_names, pattern):
    i = 1
    while True:
        name = pattern % i
        if name not in existing_names:
            return name
        i += 1


def _read_zip(f):
    d = OrderedDict()
    with ZipFile(f, 'r') as z:
        for zi in z.infolist():
            d[zi.filename] = z.read(zi)
    return d


def read_zip(path_or_file):
    if isinstance(path_or_file, basestring):
        with open(path_or_file, 'rb') as f:
            return _read_zip(f)
    else:
        return _read_zip(path_or_file)


class Document(object):
    LVL_XPATH_TEMPL = ('./w:abstractNum[@w:abstractNumId="%s"]/'
                       'w:lvl[@w:ilvl="%s"]'.replace('w:', ns.w('')))
    A_NUMID_XPATH_TEMPL = ('./w:num[@w:numId="%s"]/w:abstractNumId'
                           .replace('w:', ns.w('')))
    def __init__(self, path_or_file):
        self.z = read_zip(path_or_file)
        self.document = get_part(self.z, MAGIC_WORD + '/document.xml')
        self.numbering = get_part(self.z, MAGIC_WORD + '/numbering.xml')
        self.footnotes = get_part(self.z, MAGIC_WORD + '/footnotes.xml')
        self.endnotes = get_part(self.z, MAGIC_WORD + '/endnotes.xml')

    @staticmethod
    def _get_by_id(id, xs):  # pylint: disable=W0622
        return next(x for x in xs if id == x.attrib[ns.w('id')])

    def get_footnote(self, id):   # pylint: disable=W0622
        return self._get_by_id(id, self.footnotes.e)

    def get_endnote(self, id):  # pylint: disable=W0622
        return self._get_by_id(id, self.endnotes.e)

    def get_num_style(self, numid, level):
        numid_xpath = self.A_NUMID_XPATH_TEMPL % numid
        abstract_num_id = self.numbering.e.find(numid_xpath).attrib[ns.w('val')]
        lvl_xpath = self.LVL_XPATH_TEMPL % (abstract_num_id, level)
        lvl, = self.numbering.e.iterfind(lvl_xpath)
        numFmt = val(lvl, ns.w('numFmt'))
        lvlText = val(lvl, ns.w('lvlText'))
        return NumStyle(numFmt=numFmt, lvlText=lvlText)


    def get_or_add_extn(self, mime_type):
        path = '[Content_Types].xml'
        e = to_etree(self.z.get(path))
        ctns = 'http://schemas.openxmlformats.org/package/2006/content-types'
        default = e.xpath('./ct:Default[@ContentType="%s"]/@Extension' % mime_type,  # pylint: disable=C0301
                          namespaces={'ct': ctns})
        if len(default) == 1:
            return default[0]
        extn = guess_extension(mime_type)
        default = e.xpath('./ct:Default[@Extension="%s"]' % extn,
                          namespaces={'ct': ctns})
        assert len(default) == 0  # XXX(ash): handle this case more gracefully
        tup = ('Default', {'ContentType': mime_type, 'Extension': extn}, [])
        e[:0] = [tup2etree(tup, {None: ctns})]
        self.z[path] = etree2s(e)
        return extn


    def add_image(self, f, mime_type):
        extn = self.get_or_add_extn(mime_type)

        img = f.read()

        p = fresh_name(set(self.z.keys()),
                       MAGIC_WORD + '/media/image%d.' + extn)
        self.z[p] = img

        # XXX(ash): why do we have to relativize the targets
        rel_p = p.split('/', 1)[1]
        rid = fresh_name(set(self.document.rels), 'rId%d')
        self.document.rels[rid] = tup2etree(
            ('Relationship', {'Target': rel_p,
                              'Type': IMAGE_REL_URI,
                              'Id': rid}, []))

        return rid

    def get_images(self):
        # XXX(ash): what about the rels of the other parts...
        images = dict((id, r.attrib['Target'])
                      for (id, r) in self.document.rels.iteritems()
                      if r.attrib['Type'] == IMAGE_REL_URI)
        includes = dict((id, StringIO(self.z[MAGIC_WORD + '/' + fn]))
                        for id, fn in images.items())
        return includes

    def get_rels_for(self, part):
        return getattr(self, part).rels

    def save(self, f):
        replacements = {}
        for name in ['document', 'numbering', 'footnotes', 'endnotes']:
            part = getattr(self, name)
            if part.e is not None:
                replacements[part.path] = etree2s(part.e, decl=True)
            if part.rels:
                replacements[part.rels_path] = rels2s(part.rels)
        with ZipFile(f, 'w') as outz:
            for filename, contents in self.z.items():
                replacement = replacements.get(filename, None)
                outz.writestr(
                    filename, replacement if replacement else contents)


class Measurement(object):
    scale = None

    def __init__(self, value):
        self.value = int(value)

    @property
    def emu(self):
        return Emu(self.value * self.scale)

    @property
    def real(self):
        return self.value


class Px(Measurement):
    scale = 12700


class Emu(Measurement):
    scale = 1


class Twips(Measurement):
    scale = 635

SectPr = namedtuple('sectPr', 'page_width right_margin left_margin')


def parse_sectPr(e):  # pylint: disable=C0103
    assert e.tag == ns.w('sectPr')

    d = dict(
        page_width=map(ns.w, ['pgSz', 'w']),
        left_margin=map(ns.w, ['pgMar', 'left']),
        right_margin=map(ns.w, ['pgMar', 'right']),
    )
    return SectPr(**{k: Twips(val(e, *p)) for (k, p) in d.items()})


def is_possibly_docx(bytes):  # pylint: disable=W0622
    if not bytes.startswith('PK\3\4'):
        return False # not a zip
    # The officeopenxml container format is unfortunatley moronically designed
    # so we can't just look for some fixed prefix
    names = ZipFile(StringIO(bytes)).namelist()
    return ('[Content_Types].xml' in names
            and any(name.startswith(MAGIC_WORD + '/') for name in names))
