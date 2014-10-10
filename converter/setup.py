from setuptools import setup

setup(name='typesetr-converter',
      version=1.0,
      description='Convert google doc .odt files into pdfs',
      author='LShift',
      packages=['converter'],
      install_requires=[
          'html5lib==1.0b3',
          'cssutils==1.0',
          'jellyfish==0.2.2',
          'lxml==3.3.3',
          'misaka==1.0.2',
          'Pillow==2.5.0',
          'pybtex==0.17',
          'Pygments==1.6',
          'python-dateutil==1.4.1',
          'PyYAML==3.10',
          'regex==2014.02.19',
          'requests==2.2.1',
          'ipdb==0.8',
          'beautifulsoup4==4.3.2',
          ],
      scripts=['gdoc-to'],
      include_files=['share/template.html'],
     )