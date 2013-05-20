#!/usr/bin/env python
import sys

print("\nINSTALLED VERSIONS")
print("------------------")
print("Python: %d.%d.%d.%s.%s" % sys.version_info[:])
try:
    import os
    (sysname, nodename, release, version, machine) = os.uname()
    print("OS: %s %s %s %s" % (sysname, release, version,machine))
    print("LC_ALL: %s" % os.environ.get('LC_ALL',"None"))
    print("LANG: %s" % os.environ.get('LANG',"None"))
except:
    pass

print("")
try:
    import Cython
    print("Cython: %s" % Cython.__version__)
except:
    print("Cython: Not installed")

try:
    import numpy
    print("Numpy: %s" % numpy.version.version)
except:
    print("Numpy: Not installed")

try:
    import scipy
    print("Scipy: %s" % scipy.version.version)
except:
    print("Scipy: Not installed")

try:
    import statsmodels
    print("statsmodels: %s" % statsmodels.__version__)
except:
    print("statsmodels: Not installed")
try:
    import patsy
    print("    patsy: %s" % patsy.__version__)
except:
    print("    patsy: Not installed")

try:
    import scikits.timeseries as ts
    print("scikits.timeseries: %s" % ts.__version__)
except:
    print("scikits.timeseries: Not installed")

try:
    import dateutil
    print("dateutil: %s" % dateutil.__version__)
except:
    print("dateutil: Not installed")

try:
    import pytz
    print("pytz: %s" % pytz.VERSION)
except:
    print("pytz: Not installed")

try:
    import tables
    print("PyTables: %s" % tables.__version__)
except:
    print("PyTables: Not Installed")

try:
    import numexpr
    print("    numexpr: %s" % numexpr.__version__)
except:
    print("    numexpr: Not Installed")

try:
    import matplotlib
    print("matplotlib: %s" % matplotlib.__version__)
except:
    print("matplotlib: Not installed")

try:
    import openpyxl
    print("openpyxl: %s" % openpyxl.__version__)
except:
    print("openpyxl: Not installed")

try:
    import xlrd
    print("xlrd: %s" % xlrd.__VERSION__)
except:
    print("xlrd: Not installed")

try:
    import xlwt
    print("xlwt: %s" % xlwt.__VERSION__)
except:
    print("xlwt: Not installed")

try:
    import sqlalchemy
    print("sqlalchemy: %s" % sqlalchemy.__version__)
except:
    print("sqlalchemy: Not installed")

try:
    import lxml
    from lxml import etree
    print("lxml: %s" % etree.__version__)
except:
    print("lxml: Not installed")

try:
    import bs4
    print("bs4: %s" % bs4.__version__)
except:
    print("bs4: Not installed")

try:
    import html5lib
    print("html5lib: %s" % html5lib.__version__)
except:
    print("html5lib: Not installed")

print("\n")
