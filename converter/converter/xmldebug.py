import regex as re

from lxml import etree

def all_tag_types(xml, short=False):
    def gen(xml):
        yield xml.tag if not short else xml.tag.split('}', 1)[1]
        for x in xml.iterchildren():
            for y in gen(x):
                yield y
    return set(gen(xml))

STRIP_REX = re.compile(r'''(?x)
                           (?:\s+(?:
                              style:[\w-]+-(?:asian|complex))|
                              xmlns:[\w-]+
                           )="[^"]+"
                          ''')
def ppxml(xml, strip=1): # pylint: disable=C0103
    """Pretty print Open Office xml fragments humand-readably."""
    s = etree.tostring(xml, pretty_print=True, encoding='UTF-8')
    if strip:
        s = STRIP_REX.sub(' ', s)
        for r in ['fo:font-style="normal"',
                  'fo:font-weight="normal"',
                  'fo:color="#000000"',
                  'style:font-name="Arial"',
                  'style:text-line-through-style="none"',
                  'fo:font-size="11pt"',
                  'style:text-underline-style="none"']:
            s = s.replace(r, ' ')
    return s
