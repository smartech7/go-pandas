# pylint: disable=E1101,E1103,W0232

""" manage legacy pickle tests """

from datetime import datetime, timedelta
import operator
import pickle
import unittest
import nose
import os

import numpy as np
import pandas.util.testing as tm
import pandas as pd

class TestPickle(unittest.TestCase):
    _multiprocess_can_split_ = True

    def setUp(self):
        from pandas.io.tests.generate_legacy_pickles import create_data
        self.data = create_data()

    def compare(self, vf):

        fh = open(vf,'rb')
        data = pickle.load(fh)
        fh.close()

        for typ, dv in data.items():
            for dt, result in dv.items():

                expected = self.data[typ][dt]

                comparator = getattr(tm,"assert_%s_equal" % typ)
                comparator(result,expected)

    def test_read_pickles_0_10_1(self):

        pth = tm.get_data_path('legacy_pickle/0.10.1')
        for f in os.listdir(pth):
            vf = os.path.join(pth,f)
            self.compare(vf)

    def test_read_pickles_0_11_0(self):

        pth = tm.get_data_path('legacy_pickle/0.11.0')
        for f in os.listdir(pth):
            vf = os.path.join(pth,f)
            self.compare(vf)

if __name__ == '__main__':
    import nose
    nose.runmodule(argv=[__file__, '-vvs', '-x', '--pdb', '--pdb-failure'],
                   # '--with-coverage', '--cover-package=pandas.core'],
                   exit=False)
