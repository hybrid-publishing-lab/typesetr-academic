import pprint

def write(out_file, style_template, bib, # pylint: disable=R0913,W0613
          meta, parsed_body, transclusions):
    head = meta.items()
    transclusions, style_template  # unused ; pylint: disable=W0104
    print >> out_file, pprint.pformat((head, parsed_body))
