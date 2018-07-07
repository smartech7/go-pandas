.. _extending:

****************
Extending Pandas
****************

While pandas provides a rich set of methods, containers, and data types, your
needs may not be fully satisfied. Pandas offers a few options for extending
pandas.

.. _extending.register-accessors:

Registering Custom Accessors
----------------------------

Libraries can use the decorators
:func:`pandas.api.extensions.register_dataframe_accessor`,
:func:`pandas.api.extensions.register_series_accessor`, and
:func:`pandas.api.extensions.register_index_accessor`, to add additional
"namespaces" to pandas objects. All of these follow a similar convention: you
decorate a class, providing the name of attribute to add. The class's
``__init__`` method gets the object being decorated. For example:

.. code-block:: python

   @pd.api.extensions.register_dataframe_accessor("geo")
   class GeoAccessor(object):
       def __init__(self, pandas_obj):
           self._obj = pandas_obj

       @property
       def center(self):
           # return the geographic center point of this DataFrame
           lat = self._obj.latitude
           lon = self._obj.longitude
           return (float(lon.mean()), float(lat.mean()))

       def plot(self):
           # plot this array's data on a map, e.g., using Cartopy
           pass

Now users can access your methods using the ``geo`` namespace:

      >>> ds = pd.DataFrame({'longitude': np.linspace(0, 10),
      ...                    'latitude': np.linspace(0, 20)})
      >>> ds.geo.center
      (5.0, 10.0)
      >>> ds.geo.plot()
      # plots data on a map

This can be a convenient way to extend pandas objects without subclassing them.
If you write a custom accessor, make a pull request adding it to our
:ref:`ecosystem` page.

.. _extending.extension-types:

Extension Types
---------------

.. versionadded:: 0.23.0

.. warning::

   The :class:`pandas.api.extensions.ExtensionDtype` and :class:`pandas.api.extensions.ExtensionArray` APIs are new and
   experimental. They may change between versions without warning.

Pandas defines an interface for implementing data types and arrays that *extend*
NumPy's type system. Pandas itself uses the extension system for some types
that aren't built into NumPy (categorical, period, interval, datetime with
timezone).

Libraries can define a custom array and data type. When pandas encounters these
objects, they will be handled properly (i.e. not converted to an ndarray of
objects). Many methods like :func:`pandas.isna` will dispatch to the extension
type's implementation.

If you're building a library that implements the interface, please publicize it
on :ref:`ecosystem.extensions`.

The interface consists of two classes.

:class:`~pandas.api.extensions.ExtensionDtype`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A :class:`pandas.api.extensions.ExtensionDtype` is similar to a ``numpy.dtype`` object. It describes the
data type. Implementors are responsible for a few unique items like the name.

One particularly important item is the ``type`` property. This should be the
class that is the scalar type for your data. For example, if you were writing an
extension array for IP Address data, this might be ``ipaddress.IPv4Address``.

See the `extension dtype source`_ for interface definition.

.. versionadded:: 0.24.0

:class:`pandas.api.extension.ExtensionDtype` can be registered to pandas to allow creation via a string dtype name.
This allows one to instantiate ``Series`` and ``.astype()`` with a registered string name, for
example ``'category'`` is a registered string accessor for the ``CategoricalDtype``.

See the `extension dtype dtypes`_ for more on how to register dtypes.

:class:`~pandas.api.extensions.ExtensionArray`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This class provides all the array-like functionality. ExtensionArrays are
limited to 1 dimension. An ExtensionArray is linked to an ExtensionDtype via the
``dtype`` attribute.

Pandas makes no restrictions on how an extension array is created via its
``__new__`` or ``__init__``, and puts no restrictions on how you store your
data. We do require that your array be convertible to a NumPy array, even if
this is relatively expensive (as it is for ``Categorical``).

They may be backed by none, one, or many NumPy arrays. For example,
``pandas.Categorical`` is an extension array backed by two arrays,
one for codes and one for categories. An array of IPv6 addresses may
be backed by a NumPy structured array with two fields, one for the
lower 64 bits and one for the upper 64 bits. Or they may be backed
by some other storage type, like Python lists.

See the `extension array source`_ for the interface definition. The docstrings
and comments contain guidance for properly implementing the interface.

.. _extending.extension.operator:

:class:`~pandas.api.extensions.ExtensionArray` Operator Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. versionadded:: 0.24.0

By default, there are no operators defined for the class :class:`~pandas.api.extensions.ExtensionArray`.
There are two approaches for providing operator support for your ExtensionArray:

1. Define each of the operators on your ``ExtensionArray`` subclass.
2. Use an operator implementation from pandas that depends on operators that are already defined
   on the underlying elements (scalars) of the ExtensionArray.

For the first approach, you define selected operators, e.g., ``__add__``, ``__le__``, etc. that
you want your ``ExtensionArray`` subclass to support.

The second approach assumes that the underlying elements (i.e., scalar type) of the ``ExtensionArray``
have the individual operators already defined.  In other words, if your ``ExtensionArray``
named ``MyExtensionArray`` is implemented so that each element is an instance
of the class ``MyExtensionElement``, then if the operators are defined
for ``MyExtensionElement``, the second approach will automatically
define the operators for ``MyExtensionArray``.

A mixin class, :class:`~pandas.api.extensions.ExtensionScalarOpsMixin` supports this second
approach.  If developing an ``ExtensionArray`` subclass, for example ``MyExtensionArray``,
can simply include ``ExtensionScalarOpsMixin`` as a parent class of ``MyExtensionArray``,
and then call the methods :meth:`~MyExtensionArray._add_arithmetic_ops` and/or
:meth:`~MyExtensionArray._add_comparison_ops` to hook the operators into
your ``MyExtensionArray`` class, as follows:

.. code-block:: python

    class MyExtensionArray(ExtensionArray, ExtensionScalarOpsMixin):
        pass

    MyExtensionArray._add_arithmetic_ops()
    MyExtensionArray._add_comparison_ops()

Note that since ``pandas`` automatically calls the underlying operator on each
element one-by-one, this might not be as performant as implementing your own
version of the associated operators directly on the ``ExtensionArray``.

.. _extending.extension.testing:

Testing Extension Arrays
^^^^^^^^^^^^^^^^^^^^^^^^

We provide a test suite for ensuring that your extension arrays satisfy the expected
behavior. To use the test suite, you must provide several pytest fixtures and inherit
from the base test class. The required fixtures are found in
https://github.com/pandas-dev/pandas/blob/master/pandas/tests/extension/conftest.py.

To use a test, subclass it:

.. code-block:: python

   from pandas.tests.extension import base

   class TestConstructors(base.BaseConstructorsTests):
       pass


See https://github.com/pandas-dev/pandas/blob/master/pandas/tests/extension/base/__init__.py
for a list of all the tests available.

.. _extension dtype dtypes: https://github.com/pandas-dev/pandas/blob/master/pandas/core/dtypes/dtypes.py
.. _extension dtype source: https://github.com/pandas-dev/pandas/blob/master/pandas/core/dtypes/base.py
.. _extension array source: https://github.com/pandas-dev/pandas/blob/master/pandas/core/arrays/base.py

.. _extending.subclassing-pandas:

Subclassing pandas Data Structures
----------------------------------

.. warning:: There are some easier alternatives before considering subclassing ``pandas`` data structures.

  1. Extensible method chains with :ref:`pipe <basics.pipe>`

  2. Use *composition*. See `here <http://en.wikipedia.org/wiki/Composition_over_inheritance>`_.

  3. Extending by :ref:`registering an accessor <extending.register-accessors>`

  4. Extending by :ref:`extension type <extending.extension-types>`

This section describes how to subclass ``pandas`` data structures to meet more specific needs. There are two points that need attention:

1. Override constructor properties.
2. Define original properties

.. note::

   You can find a nice example in `geopandas <https://github.com/geopandas/geopandas>`_ project.

Override Constructor Properties
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each data structure has several *constructor properties* for returning a new
data structure as the result of an operation. By overriding these properties,
you can retain subclasses through ``pandas`` data manipulations.

There are 3 constructor properties to be defined:

* ``_constructor``: Used when a manipulation result has the same dimensions as the original.
* ``_constructor_sliced``: Used when a manipulation result has one lower dimension(s) as the original, such as ``DataFrame`` single columns slicing.
* ``_constructor_expanddim``: Used when a manipulation result has one higher dimension as the original, such as ``Series.to_frame()`` and ``DataFrame.to_panel()``.

Following table shows how ``pandas`` data structures define constructor properties by default.

===========================  ======================= =============
Property Attributes          ``Series``              ``DataFrame``
===========================  ======================= =============
``_constructor``             ``Series``              ``DataFrame``
``_constructor_sliced``      ``NotImplementedError`` ``Series``
``_constructor_expanddim``   ``DataFrame``           ``Panel``
===========================  ======================= =============

Below example shows how to define ``SubclassedSeries`` and ``SubclassedDataFrame`` overriding constructor properties.

.. code-block:: python

   class SubclassedSeries(Series):

       @property
       def _constructor(self):
           return SubclassedSeries

       @property
       def _constructor_expanddim(self):
           return SubclassedDataFrame

   class SubclassedDataFrame(DataFrame):

       @property
       def _constructor(self):
           return SubclassedDataFrame

       @property
       def _constructor_sliced(self):
           return SubclassedSeries

.. code-block:: python

   >>> s = SubclassedSeries([1, 2, 3])
   >>> type(s)
   <class '__main__.SubclassedSeries'>

   >>> to_framed = s.to_frame()
   >>> type(to_framed)
   <class '__main__.SubclassedDataFrame'>

   >>> df = SubclassedDataFrame({'A', [1, 2, 3], 'B': [4, 5, 6], 'C': [7, 8, 9]})
   >>> df
      A  B  C
   0  1  4  7
   1  2  5  8
   2  3  6  9

   >>> type(df)
   <class '__main__.SubclassedDataFrame'>

   >>> sliced1 = df[['A', 'B']]
   >>> sliced1
      A  B
   0  1  4
   1  2  5
   2  3  6
   >>> type(sliced1)
   <class '__main__.SubclassedDataFrame'>

   >>> sliced2 = df['A']
   >>> sliced2
   0    1
   1    2
   2    3
   Name: A, dtype: int64
   >>> type(sliced2)
   <class '__main__.SubclassedSeries'>

Define Original Properties
^^^^^^^^^^^^^^^^^^^^^^^^^^

To let original data structures have additional properties, you should let ``pandas`` know what properties are added. ``pandas`` maps unknown properties to data names overriding ``__getattribute__``. Defining original properties can be done in one of 2 ways:

1. Define ``_internal_names`` and ``_internal_names_set`` for temporary properties which WILL NOT be passed to manipulation results.
2. Define ``_metadata`` for normal properties which will be passed to manipulation results.

Below is an example to define two original properties, "internal_cache" as a temporary property and "added_property" as a normal property

.. code-block:: python

   class SubclassedDataFrame2(DataFrame):

       # temporary properties
       _internal_names = pd.DataFrame._internal_names + ['internal_cache']
       _internal_names_set = set(_internal_names)

       # normal properties
       _metadata = ['added_property']

       @property
       def _constructor(self):
           return SubclassedDataFrame2

.. code-block:: python

   >>> df = SubclassedDataFrame2({'A': [1, 2, 3], 'B': [4, 5, 6], 'C': [7, 8, 9]})
   >>> df
      A  B  C
   0  1  4  7
   1  2  5  8
   2  3  6  9

   >>> df.internal_cache = 'cached'
   >>> df.added_property = 'property'

   >>> df.internal_cache
   cached
   >>> df.added_property
   property

   # properties defined in _internal_names is reset after manipulation
   >>> df[['A', 'B']].internal_cache
   AttributeError: 'SubclassedDataFrame2' object has no attribute 'internal_cache'

   # properties defined in _metadata are retained
   >>> df[['A', 'B']].added_property
   property
