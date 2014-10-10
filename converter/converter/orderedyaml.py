# adapted from
# <http://blog.elsdoerfer.name/2012/07/26/make-pyyaml-output-an-ordereddict/>
# FIXME: check w/ author for License
"""Make PyYAML output an OrderedDict.

It will do so fine if you use yaml.dump(), but that generates ugly,
non-standard YAML code.

To use yaml.safe_dump(), you need the following.
"""
from collections import OrderedDict
from functools import partial
import yaml
# we want to re-export, so shut up pylint and do a * import
from yaml import * # pylint: disable=W0401,W0614


# extracted from https://gist.github.com/317164,
def construct_odict(loader, node):
    omap = OrderedDict()
    yield omap
    if not isinstance(node, yaml.MappingNode):
        raise yaml.constructor.ConstructorError(
            "while constructing an ordered map",
            node.start_mark,
            "expected a map, but found %s" % node.id, node.start_mark
        )
    loader.flatten_mapping(node)
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        value = loader.construct_object(value_node)
        try:
            hash(key)
        except TypeError, exc:
            raise yaml.constructor.ConstructorError(
                'while constructing an ordered map',
                node.start_mark,
                'found unacceptable key (%s)' % exc,
                key_node.start_mark)
        omap[key] = value

yaml.add_constructor(u'tag:yaml.org,2002:map', construct_odict)

def represent_odict(dump, tag, mapping, flow_style=None):
    """Like BaseRepresenter.represent_mapping, but does not issue the sort().
    """
    value = []
    node = yaml.MappingNode(tag, value, flow_style=flow_style)
    if dump.alias_key is not None:
        dump.represented_objects[dump.alias_key] = node
    best_style = True
    if hasattr(mapping, 'items'):
        mapping = mapping.items()
    for item_key, item_value in mapping:
        node_key = dump.represent_data(item_key)
        node_value = dump.represent_data(item_value)
        if not (isinstance(node_key, yaml.ScalarNode) and not node_key.style):
            best_style = False
        if not (isinstance(node_value, yaml.ScalarNode)
                and not node_value.style):
            best_style = False
        value.append((node_key, node_value))
    if flow_style is None:
        if dump.default_flow_style is not None:
            node.flow_style = dump.default_flow_style
        else:
            node.flow_style = best_style
    return node

yaml.SafeDumper.add_representer(
    OrderedDict,
    lambda dumper, value:
    represent_odict(dumper, u'tag:yaml.org,2002:map', value))
## yaml.safe_dump(data, default_flow_style=False)
# pylint: disable=C0103
add_representer = yaml.SafeDumper.add_representer
dump = partial(yaml.safe_dump, default_flow_style=False)
