from . import orderedyaml as yaml # pylint: disable=E0611

def write(out_file, style_template, bib, # pylint: disable=R0913,W0613
          meta, parsed_body, transclusions):
    parsed_body, style_template, transclusions  # unused; pylint: disable=W0104
    print >> out_file, yaml.dump(meta.d)
