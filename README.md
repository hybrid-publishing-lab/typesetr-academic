About:
-----

Typesetr Converter is the core conversion engine of the typesetr.consortium.io Webservice developed by the Hybrid Publishing Consortium in cooperation with LShift Ltd.

The Hybrid Publishing Consortium is a project of the Hybrid Publishing Lab in collaboration with partners and associates. The Hybrid Publishing Lab is part of the Leuphana University of Lüneburg Innovation-Incubator, financed by the European Regional Development Fund and co-funded by the German federal state of Lower Saxony.

see: 
LINK
LINK

Licenses:
--------



Typesetr-converter
------------------
    Copyright (C) 2014  LShift Ltd

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License along
    with this program. If not, see <http://www.gnu.org/licenses/>.

    http://www.gnu.org/licenses/agpl-3.0.txt

	digest.py, docerror.py, docx_parser.py, docxlite.py, dublin.py, endnotify.py, epub_writer.py
	exit_code.py, ezmatch.py, gdoc-to, gdoc_converter.py, highlight.py, html_parser.py, html_writer.py
	lang.py, latex_writer.py, literal.py, lxmlutil.py, markdown_parser.py, meta_writer.py, metainfo.py
 	mimetype.py, odt_parser.py, odt_writer.py, orderedyaml.py, pickle_writer.py, postprocess.py
 	preprocess.py, sectionize.py, setup.py, spellsuggest.py, stytempl.py, transclusions.py, unparse.py,
 	utils.py, xml_namespaces.py, xmldebug.py, xmltools.py

------

Templates
---------
	Copyright (C) 2014 Universität Leuphana Lüneburg

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License along
    with this program. If not, see <http://www.gnu.org/licenses/>.

    http://www.gnu.org/licenses/agpl-3.0.txt

------

Prerequisites
-------------

 - Ubuntu 12.04 Precise (untested on other plattforms)
 - Python 2.7
 - at least 3GB of free Space ( Texlive :/ )

The package manager will solve all dependancies.

Package Installation
------------

The easyiest way to install typesetr-converter is download the DEBs via apt 

Add the following lines to your /etc/apt/sources.list:

      deb https://repo.consortium.io/apt/debian precise main

Execute following lines

      wget -q https://repo.consortium.io/apt/debian/dists/precise/typesetr.gpg.key -O- | sudo apt-key add -

	  sudo apt-get update
      sudo apt-get install typesetr-core typesetr-fonts typesetr-styles typesetr-texlive


Manual Installation or installations other than Ubuntu 12.04
------------------------------------------------------------

Not available yet ... will follow shortly.

Development
-----------

Documentation
-------------
Link to Readthedocs

Support
-------
Zendesk







