import sys
from pprint import pprint

# read apk
#import androguard.core.bytecodes.apk as apk
#a = apk.APK(sys.argv[1])

import androguard.core.bytecodes.dvm as dvm
from androguard.core.analysis.analysis import *

import executor
import descriptors


# XXX must be library for this
def has_field_name(s):
    """
    fieldName -> hasFieldName
    """
    return 'has' + s[:1].upper() + s[1:]


class Reprotobuf(object):
    def __init__(self, classes_dex):
        self.dvm = dvm.DalvikVMFormat(classes_dex)
        self.vma = uVMAnalysis(self.dvm)
        self.tree = {}
        self.files = {}

    @classmethod
    def from_classes_dex(cls, filename):
        with open(sys.argv[1], 'rb') as f:
            classes_dex = f.read()
        return cls(classes_dex)

    def get_proto_classes(self):
        def is_proto(cls):
            return ('MessageNano;' in cls.get_superclassname() and
                    'abstract' not in cls.get_access_flags_string())
        return filter(is_proto, self.dvm.get_classes())

    def add_class(self, classname, fields):
        # build tree
        parts = classname.split('$')
        node = self.tree
        for part in parts:
            subnodes = node.setdefault('sub', {})
            node = subnodes.setdefault(part, {})
        node['class'] = classname
        #node['fields'] = fields

    def process_classes(self):
        class_analyzer = MessageNanoAnalyzer(self)
        proto_classes = self.get_proto_classes()
        for cls in proto_classes:
            name = descriptors.extract_classname(cls.get_name())
            fields = class_analyzer.analyze(cls)
            self.add_class(name, fields)

    def structure_packages(self):
        for name in self.tree['sub']:
            # extract package and outer name
            parts = name.split('/')
            filename_part = parts.pop()
            package = '.'.join(parts)
            filename = filename_part + '.proto'
            file_properties = {
                    'name': filename,
                    'package': package,
                    'options': {},
                    }
            # if there's a class at this level
            if 'class' in self.tree['sub'][name]:
                file_properties['options']['java_multiple_files'] = True
                file_properties['messages'] = {
                        filename_part: self.tree['sub'][name]
                        }
            else:
                file_properties['messages'] = self.tree['sub'][name]
            # add this file to our list
            assert filename not in self.files
            self.files[filename] = file_properties


class MessageNanoAnalyzer(object):
    def __init__(self, workspace):
        self.workspace = workspace

    def get_fields_from_class(self, cls):
        """
        Deduce fields by inspecting the fields of the Java class.
        """
        # fetch all the fields
        fields = {}
        for field in cls.get_fields():
            name = field.get_name()
            fields[name] = {
                    'name': name,
                    'descriptor': field.get_descriptor(),
                    'rule': 'required',
                    }
        # deduce optional ones from has* fields
        optional = []
        for name in fields:
            if has_field_name(name) in fields:
                optional.append(name)
        # mark the optional fields, and remove
        for name in optional:
            del fields[has_field_name(name)]
            fields[name]['rule'] = 'optional'
        # remove _emptyArray if it exists
        fields.pop('_emptyArray', None)
        # deduce protobuf types from descriptors
        for properties in fields.values():
            descriptor = properties['descriptor']
            protobuf_type = descriptors.to_protobuf_type(descriptor)
            properties.update(protobuf_type)
        return fields

    def get_tags_from_class(self, cls):
        methods = [m for m in cls.get_methods() if m.get_name() == 'writeTo']
        if len(methods) == 0:
            return {}

        method = self.workspace.vma.get_method(methods[0])
        basic_blocks = method.basic_blocks.gets()

        e = executor.WriteToExecutor()

        for bb in basic_blocks:
            for inst in bb.get_instructions():
                e.run(inst)

        return e.get_tags()

    def analyze(self, cls):
        # deduce fields
        fields = self.get_fields_from_class(cls)
        # deduce tags
        tag_map = self.get_tags_from_class(cls)
        for name, tag in tag_map.items():
            assert name in fields
            fields[name]['tag'] = tag
        # check we got a tag for everything
        for properties in fields.values():
            assert 'tag' in properties
        return fields


# main ---------------------------------------------------------

workspace = Reprotobuf.from_classes_dex(sys.argv[1])
workspace.process_classes()
workspace.structure_packages()
pprint(workspace.files)
