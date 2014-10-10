class Ns(object): # pylint: disable=R0902
    "Xml namespace helper (good grief, why do I have to do crap like this?)"
    def __init__(self, ns_dict):
        # just there to make pylint happy
        self.style = self.fo = self.text = self.office = self.draw = \
                     self.table = self.dc = self.xlink = self.w = \
                     self.r = self.m = self.wp = lambda *x: None
        self.dict = ns_dict
        for k in self.dict:
            setattr(self, k, ("{%s}" % self.dict[k]).__add__)

    def __str__(self):
        return " ".join(map('xmlns:%s="%s"'.__mod__, self.dict.items()))

odt_ns = Ns({  # pylint: disable=C0103
    # openoffice odt namespaces
    'style': 'urn:oasis:names:tc:opendocument:xmlns:style:1.0',
    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
    'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',

    # openoffice crudified standard namespaces
    'fo': 'urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0',
    'svg': 'urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0',

    # general stands
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xlink': 'http://www.w3.org/1999/xlink',
    'xml': 'http://www.w3.org/XML/1998/namespace',
})


docx_ns = Ns({  # pylint: disable=C0103
    # office openxml, i.e. word
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
    'lc': 'http://schemas.openxmlformats.org/drawingml/2006/lockedCanvas',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'o': 'urn:schemas-microsoft-com:office:office',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'sl': 'http://schemas.openxmlformats.org/schemaLibrary/2006/main',
    'v': 'urn:schemas-microsoft-com:vml',
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w10': 'urn:schemas-microsoft-com:office:word',
    'wne': 'http://schemas.microsoft.com/office/word/2006/wordml',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',  # pylint: disable=C0301
    'wpg': 'http://schemas.microsoft.com/office/word/2010/wordprocessingGroup',
    'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
})
