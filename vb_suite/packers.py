from vbench.api import Benchmark
from datetime import datetime

start_date = datetime(2013, 5, 1)

common_setup = """from pandas_vb_common import *
import os
import pandas as pd
from pandas.core import common as com

f = '__test__.msg'
def remove(f):
   try:
       os.remove(f)
   except:
       pass

index = date_range('20000101',periods=50000,freq='H')
df = DataFrame({'float1' : randn(50000),
                'float2' : randn(50000)},
               index=index)
remove(f)
"""

#----------------------------------------------------------------------
# msgpack

setup = common_setup + """
df.to_msgpack(f)
"""

packers_read_pack = Benchmark("pd.read_msgpack(f)", setup, start_date=start_date)

setup = common_setup + """
"""

packers_write_pack = Benchmark("df.to_msgpack(f)", setup, cleanup="remove(f)", start_date=start_date)

#----------------------------------------------------------------------
# pickle

setup = common_setup + """
df.to_pickle(f)
"""

packers_read_pickle = Benchmark("pd.read_pickle(f)", setup, start_date=start_date)

setup = common_setup + """
"""

packers_write_pickle = Benchmark("df.to_pickle(f)", setup, cleanup="remove(f)", start_date=start_date)

#----------------------------------------------------------------------
# csv

setup = common_setup + """
df.to_csv(f)
"""

packers_read_csv = Benchmark("pd.read_csv(f)", setup, start_date=start_date)

setup = common_setup + """
"""

packers_write_csv = Benchmark("df.to_csv(f)", setup, cleanup="remove(f)", start_date=start_date)

#----------------------------------------------------------------------
# hdf store

setup = common_setup + """
df.to_hdf(f,'df')
"""

packers_read_hdf_store = Benchmark("pd.read_hdf(f,'df')", setup, start_date=start_date)

setup = common_setup + """
"""

packers_write_hdf_store = Benchmark("df.to_hdf(f,'df')", setup, cleanup="remove(f)", start_date=start_date)

#----------------------------------------------------------------------
# hdf table

setup = common_setup + """
df.to_hdf(f,'df',table=True)
"""

packers_read_hdf_table = Benchmark("pd.read_hdf(f,'df')", setup, start_date=start_date)

setup = common_setup + """
"""

packers_write_hdf_table = Benchmark("df.to_hdf(f,'df',table=True)", setup, cleanup="remove(f)", start_date=start_date)

