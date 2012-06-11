from pandas.util.py3compat import StringIO, BytesIO
from datetime import datetime
import csv
import os
import sys
import re
import unittest
import pandas.io.data as pd
import nose

class TestYahoo(unittest.TestCase):

    def test_yahoo(self):
        """asserts that yahoo is minimally working and that it throws
        an excecption when DataReader can't get a 200 response from
        yahoo """
        start = datetime(2010,1,1)
        end = datetime(2012,1,24)
        self.assertEquals(
            pd.DataReader("F", 'yahoo', start, end)['Close'][-1],
            12.82)

        self.assertRaises(
            Exception,
            lambda: pd.DataReader("NON EXISTENT TICKER", 'yahoo', start, end))

if __name__ == '__main__':
    import nose
    nose.runmodule(argv=[__file__,'-vvs','-x','--pdb', '--pdb-failure'],
                   exit=False)
