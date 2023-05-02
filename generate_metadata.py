#!/usr/bin/env python3

import xml.etree.ElementTree


def main():
    path = './plugin.video.piped/addon.xml'
    with open(path) as f:
        addon_info = f.readlines()
        doc = xml.etree.ElementTree.fromstring(addon_info)
        result = doc.find('.//download-url').attrib['value']
        addon_file.close()
        # print(result)
        print("0.0.1")

if __name__ == "__main__":
    main()
