from vbench.api import Benchmark
from datetime import datetime

common_setup = """from pandas_vb_common import *
"""

#----------------------------------------------------------------------
# read_csv

setup1 = common_setup + """
index = [rands(10) for _ in xrange(10000)]
df = DataFrame({'float1' : randn(10000),
                'float2' : randn(10000),
                'string1' : ['foo'] * 10000,
                'bool1' : [True] * 10000,
                'int1' : np.random.randint(0, 100000, size=10000)},
               index=index)
df.to_csv('__test__.csv')
"""

read_csv_standard = Benchmark("read_csv('__test__.csv')", setup1,
                              start_date=datetime(2011, 9, 15))


#----------------------------------------------------------------------
# write_csv

setup2 = common_setup + """
index = [rands(10) for _ in xrange(10000)]
df = DataFrame({'float1' : randn(10000),
                'float2' : randn(10000),
                'string1' : ['foo'] * 10000,
                'bool1' : [True] * 10000,
                'int1' : np.random.randint(0, 100000, size=10000)},
               index=index)
"""

write_csv_standard = Benchmark("df.to_csv('__test__.csv')", setup2,
                               start_date=datetime(2011, 9, 15))

#----------------------------------
setup = common_setup + """
df = DataFrame(np.random.randn(3000, 30))
"""
frame_to_csv = Benchmark("df.to_csv('__test__.csv')", setup,
                         start_date=datetime(2011, 1, 1))

#----------------------------------
setup = common_setup + """
from pandas import concat, Timestamp

df_float  = DataFrame(np.random.randn(1000, 30),dtype='float64')
df_int    = DataFrame(np.random.randn(1000, 30),dtype='int64')
df_bool   = DataFrame(True,index=df_float.index,columns=df_float.columns)
df_object = DataFrame('foo',index=df_float.index,columns=df_float.columns)
df_dt     = DataFrame(Timestamp('20010101'),index=df_float.index,columns=df_float.columns)
df        = concat([ df_float, df_int, df_bool, df_object, df_dt ], axis=1)
"""
frame_to_csv_mixed = Benchmark("df.to_csv('__test__.csv')", setup,
                               start_date=datetime(2012, 6, 1))

#----------------------------------------------------------------------
# parse dates, ISO8601 format

setup = common_setup + """
rng = date_range('1/1/2000', periods=1000)
data = '\\n'.join(rng.map(lambda x: x.strftime("%Y-%m-%d %H:%M:%S")))
"""

stmt = ("read_csv(StringIO(data), header=None, names=['foo'], "
        "         parse_dates=['foo'])")
read_parse_dates_iso8601 = Benchmark(stmt, setup,
                                     start_date=datetime(2012, 3, 1))
