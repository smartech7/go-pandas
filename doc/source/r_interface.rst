.. currentmodule:: pandas.rpy

.. _rpy:

******************
rpy2 / R interface
******************

.. note::

   This is all highly experimental. I would like to get more people involved
   with building a nice RPy2 interface for pandas


If your computer has R and rpy2 (> 2.2) installed (which will be left to the
reader), you will be able to leverage the below functionality. On Windows,
doing this is quite an ordeal at the moment, but users on Unix-like systems
should find it quite easy. rpy2 evolves in time and the current interface is
designed for the 2.2.x series, and we recommend to use over other series 
unless you are prepared to fix parts of the code. Released packages are available
in PyPi, but should the latest code in the 2.2.x series be wanted it can be obtained with:

::

    # if installing for the first time
    hg clone http://bitbucket.org/lgautier/rpy2

    cd rpy2
    hg pull
    hg update version_2.2.x
    sudo python setup.py install

.. note::

    To use R packages with this interface, you will need to install
    them inside R yourself. At the moment it cannot install them for
    you.

Once you have done installed R and rpy2, you should be able to import
``pandas.rpy.common`` without a hitch.

Transferring R data sets into Python
------------------------------------

The **load_data** function retrieves an R data set and converts it to the
appropriate pandas object (most likely a DataFrame):


.. ipython:: python

   import pandas.rpy.common as com
   infert = com.load_data('infert')

   infert.head()

Calling R functions with pandas objects
---------------------------------------



High-level interface to R estimators
------------------------------------
