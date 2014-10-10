#-*- file-encoding: utf-8 -*-
"""A human language class (built around iso639 2 letter codes)"""
import logging as log

from converter._literal import Literal
from converter import orderedyaml as yaml # pylint: disable=E0611

__all__ = ['Lang']
# iso639 code to babel, note that this misses important languages such as
# Chinese, Japanese, Korean and Arabic (for which extra pains are required)
ISO_TO_BABEL = {
    'af': 'afrikaans',
    'id': 'indonesian',
    'ms': 'malay',
    'bg': 'bulgarian',
    'ca': 'catalan',
    'hr': 'croatian',
    'cs': 'czech',
    'da': 'danish',
    'nl': 'dutch',
    'en': 'american',
    'en-US': 'american',
    'en-UK': 'british',
    'en-CA': 'canadian',
    'en-AU': 'australian',
    'en-NZ': 'newzealand',
    'et': 'estonian',
    'fi': 'finnish',
    'fr': 'french', # frenchb appears to be a better default, but breaks w/ APA
    'fr-FR': 'french',
    'fr-CA': 'canadien',
    'fr-CH': 'french',
    'gl': 'galician',
    'de': 'ngerman', # reformed
    'de-DE': 'ngerman', # reformed
    'de-AT': 'naustrian', #reformed
    'de-CH': 'ngerman', # FIXME: no swiss support in babel
    'el': 'greek',
    'he': 'hebrew',
    'hu': 'hungarian',
    'is': 'icelandic',
    'ga': 'irish',
    'it': 'italian',
    'la': 'latin',
    'no': 'norsk',
    'pl': 'polish',
    'pt': 'portuguese',
    'pt-BR': 'brazilian',
    'ro': 'romanian',
    'ru': 'russian',
    'es': 'spanish',
    'sk': 'slovak',
    'sl': 'slovene',
    'sv': 'swedish',
    'sr': 'serbian',
    'tr': 'turkish',
    'uk': 'ukrainian',
}

class UnknownLang(ValueError):
    pass

# pylint: disable=W0231
class Lang(Literal, yaml.YAMLObject):
    """Represents a human language.

    Initialize with an iso639-1 code, which can be looked up as well:
    >>> Lang('en').code
    'en'

    You can use dialects, and look up the dialect-free variant:
    >>> Lang('en-UK').dialect_free
    Lang('en')

    >>> Lang('en') == Lang('en') and Lang('en') != Lang('en_US')
    True
    """
    def __init__(self, code):
        self.code = code.replace('_', '-')
        if self.code not in ISO_TO_BABEL:
            raise UnknownLang(code)
        self.dialect_free = (Lang(self.code.split('-')[0]) if '-' in code
                             else self)
    @classmethod
    def is_valid_lang(cls, code):
        """Is `code` a valid (and babel supported) `iso639-1` identifier?

        >>> Lang.is_valid_lang('de')
        True

        Unforunately there is currently not CJK or Arabic support:
        >>> Lang.is_valid_lang('zh')
        False
        """
        try:
            cls(code)
        except UnknownLang:
            return False
        return True
    def __repr__(self):
        return 'Lang(%r)' % self.code
    def __str__(self):
        return self.code
    to_string = __str__
    @classmethod
    def from_string(cls, s):
        return cls(s)
    def to_babel(self):
        """Return the (LaTeX) babel name for myself.

        >>> Lang('en').to_babel()
        'american'
        >>> Lang('en-UK').to_babel()
        'british'
        """
        return ISO_TO_BABEL[self.code]
    def localize(self, s):
        u"""Provide a translation for string `s`.

        (American) English roundtrips:
        >>> Lang('en').localize('Table of Contents')
        u'Table of Contents'
        >>> Lang('en-UK').localize('Table of Contents')
        u'Table of Contents'

        If no localization for a dialect is present, the localization for the
        language as such is returned.
        >>> Lang('de').localize('Table of Contents')
        u'Inhaltsverzeichnis'
        >>> Lang('de-CH').localize('Table of Contents') # fallback to 'de'
        u'Inhaltsverzeichnis'

        If no translation is present, fall back to English and warn:
        >>> Lang('ms').localize('Table of Contents')
        u'Table of Contents'
        """

        if s not in LOCALIZATIONS:
            log.error("No localization for %r", s)
        if self == EN:
            return unicode(s)
        ans = LOCALIZATIONS[s].get(self.code)
        if ans is None:
            if self.dialect_free == self:
                log.warn('No translation to %r for %r', self, s)
                return unicode(s)
            return self.dialect_free.localize(s)
        return ans

EN = Lang('en')

LOCALIZATIONS = {
    u'Author': {
        'de': u'Autor'},
    u'Title': {
        'de': u'Titel'},
    u'Date': {
        'de': u'Datum'},
    u'Short-title': {
        'de': u'Kurztitel'},
    u'Subtitle': {
        'de': u'Untertitel'},
    u'Abstract': {
        'de': u'Abstract'},
    u'ISBN': {
        'de': u'ISBN'},
    u'Printing': {
        'de': u'Druck'}, # FIXME
    u'Confidential': {
        'de': u'Vertraulich'},
    u'Draft': {
        'de': u'Entwurf'},
    u'Version': {
        'de': u'Version'},
    u'Project': {
        'de': u'Projekt'},
    u'Client': {
        'de': u'Klient'},
    u'Recipients': {
        'de': u'Empfänger'},
    U'Recipient': {
        'de': u'Empfänger'},
    u'Recipient address': {
        'de': u'Empfänger Adresse'},
    u'Opening': {
        'de': u'Eröffnung'},
    u'Subject': {
        'de': u'Betreff'},
    u'Closing': {
        'de': u'Schluss'},
    u'Signature': {
        'de': u'Unterschrift'},
    u'Place': {
        'de': u'Ort'},
    u'Keywords': {
        'de': u'Schlüsselwörter'},
    u'Thanks': {
        'de': u'Danksagungen'},
    u'Notice': {
        'de': u'Notiz'},
    u'Affiliation': {
        'de': u'Affiliation'},
    u'Terms & Conditions': {
        'de': u'AGB'},
    u'Contents': {
        'de': u'Inhalt'},
    u'Table of Contents': {
        'de': u'Inhaltsverzeichnis'},
    u'Table of contents': {
        'de': u'Inhaltsverzeichnis'},
    u'Start of Contents': {
        'de': u'Inhaltsanfang'},
    u'yes': {'de': u'ja'},
    u'no': {'de': u'nein'},
    u'Cover image': {
        'de': u'Umschlagsabbildung'},
    u'Logo': {
        'de': u'Logo'},
    u'Bibliography': {
        'de': u'Bibliographie'},
    u'Bibliography-preamble': {
        'de': u'Bibliographiepreambel'},
    u'Language': {
        'de': u'Sprache'},
    u'Section-numbering-depth': {
        'de': u'Kapitelnummerierungstiefe'},
    u'Table of contents depth': {
        'de': u'Inhaltsverzeichnisnummerierungstiefe'},
}
