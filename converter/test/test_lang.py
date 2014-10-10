from converter.lang import Lang

def test_localize():
    assert Lang('en').localize('Table of Contents') == 'Table of Contents'
    assert Lang('de').localize('Table of Contents') == 'Inhaltsverzeichnis'
    assert Lang('de-CH').localize('Table of Contents') == 'Inhaltsverzeichnis'
    assert Lang('ms').localize('Table of Contents') == 'Table of Contents'
