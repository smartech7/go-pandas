from pandas import *
import pandas as pd
from numpy.random import randn
from numpy.random import randint
import pandas.util.testing as tm
import random
import numpy as np
import threading
from importlib import import_module

try:
    from pandas.compat import range
except ImportError:
    pass

np.random.seed(1234)

# try em until it works!
for imp in ['pandas._libs.lib', 'pandas.lib', 'pandas_tseries']:
    try:
        lib = import_module(imp)
        break
    except:
        pass

try:
    Panel = Panel
except Exception:
    Panel = WidePanel

# didn't add to namespace until later
try:
    from pandas.core.index import MultiIndex
except ImportError:
    pass
