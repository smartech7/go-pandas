#include <Python.h>
#define PY_ARRAY_UNIQUE_SYMBOL UJSON_NUMPY
#include <numpy/arrayobject.h>
#include <numpy/halffloat.h>
#include <stdio.h>
#include <datetime.h>
#include <ultrajson.h>

#define EPOCH_ORD 719163

static PyObject* cls_dataframe;
static PyObject* cls_series;
static PyObject* cls_index;

typedef void *(*PFN_PyTypeToJSON)(JSOBJ obj, JSONTypeContext *ti, void *outValue, size_t *_outLen);


#if (PY_VERSION_HEX < 0x02050000)
typedef ssize_t Py_ssize_t;
#endif

typedef struct __NpyArrContext
{
	PyObject *array;
	char* dataptr;
	int curdim;         // current dimension in array's order
	int stridedim;      // dimension we are striding over
	int inc;            // stride dimension increment (+/- 1)
	npy_intp dim;
	npy_intp stride;
	npy_intp ndim;
	npy_intp index[NPY_MAXDIMS];
	PyArray_GetItemFunc* getitem;

	char** rowLabels;
	char** columnLabels;
} NpyArrContext;

typedef struct __TypeContext
{
	JSPFN_ITERBEGIN iterBegin;
	JSPFN_ITEREND iterEnd;
	JSPFN_ITERNEXT iterNext;
	JSPFN_ITERGETNAME iterGetName;
	JSPFN_ITERGETVALUE iterGetValue;
	PFN_PyTypeToJSON PyTypeToJSON;
	PyObject *newObj;
	PyObject *dictObj;
	Py_ssize_t index;
	Py_ssize_t size;
	PyObject *itemValue;
	PyObject *itemName;
	PyObject *attrList;
	char *citemName;

	JSINT64 longValue;

	NpyArrContext *npyarr;
	int transpose;
	char** rowLabels;
	char** columnLabels;
	npy_intp rowLabelsLen;
	npy_intp columnLabelsLen;

} TypeContext;

typedef struct __PyObjectEncoder
{
	JSONObjectEncoder enc;

	// pass through the NpyArrContext when encoding multi-dimensional arrays
	NpyArrContext* npyCtxtPassthru;

	// output format style for pandas data types
	int outputFormat;
	int originalOutputFormat;
} PyObjectEncoder;

#define GET_TC(__ptrtc) ((TypeContext *)((__ptrtc)->prv))

struct PyDictIterState
{
	PyObject *keys;
	size_t i;
	size_t sz;
};

enum PANDAS_FORMAT
{
	SPLIT,
	RECORDS,
	INDEX,
	COLUMNS,
	VALUES
};

//#define PRINTMARK() fprintf(stderr, "%s: MARK(%d)\n", __FILE__, __LINE__)		
#define PRINTMARK()

void initObjToJSON(void)
{
	PyDateTime_IMPORT;

	PyObject *mod_frame = PyImport_ImportModule("pandas.core.frame");
	if (mod_frame)
	{
		cls_dataframe = PyObject_GetAttrString(mod_frame, "DataFrame");
		cls_index = PyObject_GetAttrString(mod_frame, "Index");
		cls_series = PyObject_GetAttrString(mod_frame, "Series");
		Py_DECREF(mod_frame);
	}

	/* Initialise numpy API */
	import_array();
}

static void *PyIntToINT32(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	*((JSINT32 *) outValue) = PyInt_AS_LONG (obj);
	return NULL;
}

static void *PyIntToINT64(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	*((JSINT64 *) outValue) = PyInt_AS_LONG (obj);
	return NULL;
}

static void *PyLongToINT64(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	*((JSINT64 *) outValue) = GET_TC(tc)->longValue;
	return NULL;
}

static void *NpyHalfToDOUBLE(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	unsigned long ctype;
	PyArray_ScalarAsCtype(obj, &ctype);
	*((double *) outValue) = npy_half_to_double (ctype);
	return NULL;
}

static void *NpyFloatToDOUBLE(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	PyArray_CastScalarToCtype(obj, outValue, PyArray_DescrFromType(NPY_DOUBLE));
	return NULL;
}

static void *PyFloatToDOUBLE(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	*((double *) outValue) = PyFloat_AS_DOUBLE (obj);
	return NULL;
}

static void *PyStringToUTF8(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	*_outLen = PyString_GET_SIZE(obj);
	return PyString_AS_STRING(obj);
}

static void *PyUnicodeToUTF8(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	PyObject *newObj = PyUnicode_EncodeUTF8 (PyUnicode_AS_UNICODE(obj), PyUnicode_GET_SIZE(obj), NULL);

	GET_TC(tc)->newObj = newObj;

	*_outLen = PyString_GET_SIZE(newObj);
	return PyString_AS_STRING(newObj);
}

static void *NpyDateTimeToINT64(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	PyArray_CastScalarToCtype(obj, outValue, PyArray_DescrFromType(NPY_DATETIME));
	return NULL;
}

static void *PyDateTimeToINT64(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	int y, m, d, h, mn, s, days;

	y = PyDateTime_GET_YEAR(obj);
	m = PyDateTime_GET_MONTH(obj);
	d = PyDateTime_GET_DAY(obj);
	h = PyDateTime_DATE_GET_HOUR(obj);
	mn = PyDateTime_DATE_GET_MINUTE(obj);
	s = PyDateTime_DATE_GET_SECOND(obj);

	days = PyInt_AS_LONG(PyObject_CallMethod(PyDate_FromDate(y, m, 1), "toordinal", NULL)) - EPOCH_ORD + d - 1;
	*( (JSINT64 *) outValue) = (((JSINT64) ((days * 24 + h) * 60 + mn)) * 60 + s);
	return NULL;
}

static void *PyDateToINT64(JSOBJ _obj, JSONTypeContext *tc, void *outValue, size_t *_outLen)
{
	PyObject *obj = (PyObject *) _obj;
	int y, m, d, days;

	y = PyDateTime_GET_YEAR(obj);
	m = PyDateTime_GET_MONTH(obj);
	d = PyDateTime_GET_DAY(obj);

	days = PyInt_AS_LONG(PyObject_CallMethod(PyDate_FromDate(y, m, 1), "toordinal", NULL)) - EPOCH_ORD + d - 1;
	*( (JSINT64 *) outValue) = ((JSINT64) days * 86400);

	return NULL;
}

//=============================================================================
// Numpy array iteration functions 
//=============================================================================
int NpyArr_iterNextNone(JSOBJ _obj, JSONTypeContext *tc)
{
	return 0;
}

void NpyArr_iterBegin(JSOBJ _obj, JSONTypeContext *tc)
{
	PyArrayObject *obj;

	if (GET_TC(tc)->newObj)
	{
		obj = (PyArrayObject *) GET_TC(tc)->newObj;
	}
	else
	{
		obj = (PyArrayObject *) _obj;
	}

	if (PyArray_SIZE(obj) > 0)
	{
		PRINTMARK();
		NpyArrContext *npyarr = PyObject_Malloc(sizeof(NpyArrContext));
		GET_TC(tc)->npyarr = npyarr;

		if (!npyarr)
		{
			PyErr_NoMemory();
			GET_TC(tc)->iterNext = NpyArr_iterNextNone;
			return;
		}

		npyarr->array = (PyObject*) obj;
		npyarr->getitem = (PyArray_GetItemFunc*) PyArray_DESCR(obj)->f->getitem;
		npyarr->dataptr = PyArray_DATA(obj);
		npyarr->ndim = PyArray_NDIM(obj) - 1;
		npyarr->curdim = 0;

		if (GET_TC(tc)->transpose)
		{
			npyarr->dim = PyArray_DIM(obj, npyarr->ndim);
			npyarr->stride = PyArray_STRIDE(obj, npyarr->ndim);
			npyarr->stridedim = npyarr->ndim;
			npyarr->index[npyarr->ndim] = 0;
			npyarr->inc = -1;
		}
		else
		{
			npyarr->dim = PyArray_DIM(obj, 0);
			npyarr->stride = PyArray_STRIDE(obj, 0);
			npyarr->stridedim = 0;
			npyarr->index[0] = 0;
			npyarr->inc = 1;
		}

		npyarr->columnLabels = GET_TC(tc)->columnLabels;
		npyarr->rowLabels = GET_TC(tc)->rowLabels;
	}
	else 
	{
		GET_TC(tc)->iterNext = NpyArr_iterNextNone;
	}
	PRINTMARK();
}

void NpyArr_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->npyarr)
	{ 
		PyObject_Free(GET_TC(tc)->npyarr);
	}
	PRINTMARK();
}   

void NpyArrPassThru_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	PRINTMARK();
}

void NpyArrPassThru_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	PRINTMARK();   
	// finished this dimension, reset the data pointer
	NpyArrContext* npyarr = GET_TC(tc)->npyarr;
	npyarr->curdim--;
	npyarr->dataptr -= npyarr->stride * npyarr->index[npyarr->stridedim];
	npyarr->stridedim -= npyarr->inc;
	npyarr->dim = PyArray_DIM(npyarr->array, npyarr->stridedim);
	npyarr->stride = PyArray_STRIDE(npyarr->array, npyarr->stridedim);
	npyarr->dataptr += npyarr->stride;    
}  

int NpyArr_iterNextItem(JSOBJ _obj, JSONTypeContext *tc)
{
	PRINTMARK();
	NpyArrContext* npyarr = GET_TC(tc)->npyarr;

	if (npyarr->index[npyarr->stridedim] >= npyarr->dim) 
	{
		return 0;
	}

	GET_TC(tc)->itemValue = npyarr->getitem(npyarr->dataptr, npyarr->array);

	npyarr->dataptr += npyarr->stride;
	npyarr->index[npyarr->stridedim]++;
	return 1;
}

int NpyArr_iterNext(JSOBJ _obj, JSONTypeContext *tc)
{
	PRINTMARK();
	NpyArrContext *npyarr = GET_TC(tc)->npyarr;

	if (npyarr->curdim >= npyarr->ndim || npyarr->index[npyarr->stridedim] >= npyarr->dim)
	{
		// innermost dimension, start retrieving item values
		GET_TC(tc)->iterNext = NpyArr_iterNextItem;
		return NpyArr_iterNextItem(_obj, tc);
	}

	// dig a dimension deeper
	npyarr->index[npyarr->stridedim]++;

	npyarr->curdim++;
	npyarr->stridedim += npyarr->inc;
	npyarr->dim = PyArray_DIM(npyarr->array, npyarr->stridedim);
	npyarr->stride = PyArray_STRIDE(npyarr->array, npyarr->stridedim);
	npyarr->index[npyarr->stridedim] = 0;

	((PyObjectEncoder*) tc->encoder)->npyCtxtPassthru = npyarr;
	GET_TC(tc)->itemValue = npyarr->array;
	return 1;
}

JSOBJ NpyArr_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	PRINTMARK();
	return GET_TC(tc)->itemValue;
}

char *NpyArr_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	PRINTMARK();
	NpyArrContext *npyarr = GET_TC(tc)->npyarr;
	npy_intp idx;
	if (GET_TC(tc)->iterNext == NpyArr_iterNextItem)
	{
		idx = npyarr->index[npyarr->stridedim] - 1;
		*outLen = strlen(npyarr->columnLabels[idx]);
		return npyarr->columnLabels[idx];
	}
	else
	{
		idx = npyarr->index[npyarr->stridedim - npyarr->inc] - 1;
		*outLen = strlen(npyarr->rowLabels[idx]);
		return npyarr->rowLabels[idx];
	}
}

//=============================================================================
// Tuple iteration functions 
// itemValue is borrowed reference, no ref counting
//=============================================================================
void Tuple_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->index = 0;
	GET_TC(tc)->size = PyTuple_GET_SIZE( (PyObject *) obj);
	GET_TC(tc)->itemValue = NULL;
}

int Tuple_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	PyObject *item;

	if (GET_TC(tc)->index >= GET_TC(tc)->size)
	{
		return 0;
	}

	item = PyTuple_GET_ITEM (obj, GET_TC(tc)->index);

	GET_TC(tc)->itemValue = item;
	GET_TC(tc)->index ++;
	return 1;
}

void Tuple_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
}

JSOBJ Tuple_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *Tuple_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	return NULL;
}

//=============================================================================
// Dir iteration functions 
// itemName ref is borrowed from PyObject_Dir (attrList). No refcount
// itemValue ref is from PyObject_GetAttr. Ref counted
//=============================================================================
void Dir_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->attrList = PyObject_Dir(obj); 
	GET_TC(tc)->index = 0;
	GET_TC(tc)->size = PyList_GET_SIZE(GET_TC(tc)->attrList);
	PRINTMARK();
}

void Dir_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->itemValue)
	{
		Py_DECREF(GET_TC(tc)->itemValue);
		GET_TC(tc)->itemValue = NULL;
	}

	Py_DECREF( (PyObject *) GET_TC(tc)->attrList);
	PRINTMARK();
}

int Dir_iterNext(JSOBJ _obj, JSONTypeContext *tc)
{
	PyObject *obj = (PyObject *) _obj;
	PyObject *itemValue = GET_TC(tc)->itemValue;
	PyObject *itemName = NULL;


	if (itemValue)
	{
		Py_DECREF(GET_TC(tc)->itemValue);
		GET_TC(tc)->itemValue = itemValue = NULL;
	}

	for (; GET_TC(tc)->index  < GET_TC(tc)->size; GET_TC(tc)->index ++)
	{
		PyObject* attr = PyList_GET_ITEM(GET_TC(tc)->attrList, GET_TC(tc)->index);
		char* attrStr = PyString_AS_STRING(attr);

		if (attrStr[0] == '_')
		{
			PRINTMARK();
			continue;
		}

		itemValue = PyObject_GetAttr(obj, attr);
		if (itemValue == NULL)
		{
			PyErr_Clear();
			PRINTMARK();
			continue;
		}

		if (PyCallable_Check(itemValue))
		{
			Py_DECREF(itemValue);
			PRINTMARK();
			continue;
		}

		PRINTMARK();
		itemName = attr;
		break;
	}

	if (itemName == NULL)
	{
		GET_TC(tc)->index = GET_TC(tc)->size;
		GET_TC(tc)->itemValue = NULL;
		return 0;
	}

	GET_TC(tc)->itemName = itemName;
	GET_TC(tc)->itemValue = itemValue;
	GET_TC(tc)->index ++;
	
	PRINTMARK();
	return 1;
}



JSOBJ Dir_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	PRINTMARK();
	return GET_TC(tc)->itemValue;
}

char *Dir_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	PRINTMARK();
	*outLen = PyString_GET_SIZE(GET_TC(tc)->itemName);
	return PyString_AS_STRING(GET_TC(tc)->itemName);
}




//=============================================================================
// List iteration functions 
// itemValue is borrowed from object (which is list). No refcounting
//=============================================================================
void List_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->index =  0;
	GET_TC(tc)->size = PyList_GET_SIZE( (PyObject *) obj);
}

int List_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->index >= GET_TC(tc)->size)
	{
		PRINTMARK();
		return 0;
	}

	GET_TC(tc)->itemValue = PyList_GET_ITEM (obj, GET_TC(tc)->index);
	GET_TC(tc)->index ++;
	return 1;
}

void List_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
}

JSOBJ List_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *List_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	return NULL;
}

//=============================================================================
// pandas Index iteration functions 
//=============================================================================
void Index_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->index = 0;
	GET_TC(tc)->citemName = PyObject_Malloc(20 * sizeof(char));
	if (!GET_TC(tc)->citemName)
	{
		PyErr_NoMemory();
	}
	PRINTMARK();
}

int Index_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	if (!GET_TC(tc)->citemName)
	{
		return 0;
	}

	Py_ssize_t index = GET_TC(tc)->index;
	Py_XDECREF(GET_TC(tc)->itemValue);
	if (index == 0)
	{
		memcpy(GET_TC(tc)->citemName, "name", sizeof(char)*5);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "name");
	}
	else
	if (index == 1)
	{
		memcpy(GET_TC(tc)->citemName, "data", sizeof(char)*5);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "values");
	}
	else 
	{
		PRINTMARK();
		return 0;
	}

	GET_TC(tc)->index++;
	PRINTMARK();
	return 1;
}

void Index_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->citemName)
	{
		PyObject_Free(GET_TC(tc)->citemName);
	}
	PRINTMARK();
}

JSOBJ Index_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *Index_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	*outLen = strlen(GET_TC(tc)->citemName);
	return GET_TC(tc)->citemName;
}       

//=============================================================================
// pandas Series iteration functions 
//=============================================================================
void Series_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	PyObjectEncoder* enc = (PyObjectEncoder*) tc->encoder;
	GET_TC(tc)->index = 0;
	GET_TC(tc)->citemName = PyObject_Malloc(20 * sizeof(char));
	enc->outputFormat = VALUES; // for contained series
	if (!GET_TC(tc)->citemName)
	{
		PyErr_NoMemory();
	}
	PRINTMARK();
}

int Series_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	if (!GET_TC(tc)->citemName)
	{
		return 0;
	}

	Py_ssize_t index = GET_TC(tc)->index;
	Py_XDECREF(GET_TC(tc)->itemValue);
	if (index == 0)
	{
		memcpy(GET_TC(tc)->citemName, "name", sizeof(char)*5);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "name");
	}
	else
	if (index == 1)
	{
		memcpy(GET_TC(tc)->citemName, "index", sizeof(char)*6);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "index");
	}
	else
	if (index == 2)
	{
		memcpy(GET_TC(tc)->citemName, "data", sizeof(char)*5);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "values");
	}
	else 
	{
		PRINTMARK();
		return 0;
	}

	GET_TC(tc)->index++;
	PRINTMARK();
	return 1;
}

void Series_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	PyObjectEncoder* enc = (PyObjectEncoder*) tc->encoder;
	enc->outputFormat = enc->originalOutputFormat;
	if (GET_TC(tc)->citemName)
	{
		PyObject_Free(GET_TC(tc)->citemName);
	}
	PRINTMARK();
}

JSOBJ Series_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *Series_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	*outLen = strlen(GET_TC(tc)->citemName);
	return GET_TC(tc)->citemName;
}       

//=============================================================================
// pandas DataFrame iteration functions 
//=============================================================================
void DataFrame_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	PyObjectEncoder* enc = (PyObjectEncoder*) tc->encoder;
	GET_TC(tc)->index = 0;
	GET_TC(tc)->citemName = PyObject_Malloc(20 * sizeof(char));
	enc->outputFormat = VALUES; // for contained series & index
	if (!GET_TC(tc)->citemName)
	{
		PyErr_NoMemory();
	}
	PRINTMARK();
}

int DataFrame_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	if (!GET_TC(tc)->citemName)
	{
		return 0;
	}

	Py_ssize_t index = GET_TC(tc)->index;
	Py_XDECREF(GET_TC(tc)->itemValue);
	if (index == 0)
	{
		memcpy(GET_TC(tc)->citemName, "columns", sizeof(char)*8);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "columns");
	}
	else
	if (index == 1)
	{
		memcpy(GET_TC(tc)->citemName, "index", sizeof(char)*6);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "index");
	}
	else
	if (index == 2)
	{
		memcpy(GET_TC(tc)->citemName, "data", sizeof(char)*5);
		GET_TC(tc)->itemValue = PyObject_GetAttrString(obj, "values");
	}
	else 
	{
		PRINTMARK();
		return 0;
	}

	GET_TC(tc)->index++;
	PRINTMARK();
	return 1;
}

void DataFrame_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	PyObjectEncoder* enc = (PyObjectEncoder*) tc->encoder;
	enc->outputFormat = enc->originalOutputFormat;
	if (GET_TC(tc)->citemName)
	{
		PyObject_Free(GET_TC(tc)->citemName);
	}
	PRINTMARK();
}

JSOBJ DataFrame_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *DataFrame_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	*outLen = strlen(GET_TC(tc)->citemName);
	return GET_TC(tc)->citemName;
}       

//=============================================================================
// Dict iteration functions 
// itemName might converted to string (Python_Str). Do refCounting
// itemValue is borrowed from object (which is dict). No refCounting
//=============================================================================
void Dict_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->index = 0;
	PRINTMARK();
}

int Dict_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->itemName)
	{
		Py_DECREF(GET_TC(tc)->itemName);
		GET_TC(tc)->itemName = NULL;
	}


	if (!PyDict_Next ( (PyObject *)GET_TC(tc)->dictObj, &GET_TC(tc)->index, &GET_TC(tc)->itemName, &GET_TC(tc)->itemValue))
	{
		PRINTMARK();
		return 0;
	}

	if (PyUnicode_Check(GET_TC(tc)->itemName))
	{
		GET_TC(tc)->itemName = PyUnicode_EncodeUTF8 (
			PyUnicode_AS_UNICODE(GET_TC(tc)->itemName),
			PyUnicode_GET_SIZE(GET_TC(tc)->itemName),
			NULL
		);
	}
	else
	if (!PyString_Check(GET_TC(tc)->itemName))
	{
		GET_TC(tc)->itemName = PyObject_Str(GET_TC(tc)->itemName);
	}
	else 
	{
		Py_INCREF(GET_TC(tc)->itemName);
	}
	PRINTMARK();
	return 1;
}

void Dict_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	if (GET_TC(tc)->itemName)
	{
		Py_DECREF(GET_TC(tc)->itemName);
		GET_TC(tc)->itemName = NULL;
	}
	Py_DECREF(GET_TC(tc)->dictObj);
	PRINTMARK();
}

JSOBJ Dict_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->itemValue;
}

char *Dict_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	*outLen = PyString_GET_SIZE(GET_TC(tc)->itemName);
	return PyString_AS_STRING(GET_TC(tc)->itemName);
}

void NpyArr_freeLabels(char** labels, npy_intp len)
{
	npy_intp i;

	if (labels) 
	{
		for (i = 0; i < len; i++)
		{
			PyObject_Free(labels[i]);
		}
		PyObject_Free(labels);
	}
}

char** NpyArr_encodeLabels(PyArrayObject* labels, JSONObjectEncoder* enc, npy_intp num)
{
	PRINTMARK();
	npy_intp i, stride, len;
	npy_intp bufsize = 32768;
	char** ret;
	char *dataptr, *cLabel, *origend, *origst, *origoffset;
	char labelBuffer[bufsize];
	PyArray_GetItemFunc* getitem;

	if (PyArray_SIZE(labels) < num)
	{
		PyErr_SetString(PyExc_ValueError, "Label array sizes do not match corresponding data shape");
		return 0;
	}

	ret = PyObject_Malloc(sizeof(char*)*num);
	if (!ret)
	{
		PyErr_NoMemory();
		return 0;
	}

	for (i = 0; i < num; i++)
	{
		ret[i] = NULL;
	}

	origst = enc->start;
	origend = enc->end;
	origoffset = enc->offset;

	stride = PyArray_STRIDE(labels, 0);
	dataptr = PyArray_DATA(labels);  
	getitem = PyArray_DESCR(labels)->f->getitem;

	for (i = 0; i < num; i++)
	{
		cLabel = JSON_EncodeObject(getitem(dataptr, labels), enc, labelBuffer, bufsize);

		if (PyErr_Occurred() || enc->errorMsg)
		{
			NpyArr_freeLabels(ret, num);
			ret = 0;
			break;
		}

		// trim off any quotes surrounding the result
		if (*cLabel == '\"')
		{    
			cLabel++;
			enc->offset -= 2;
			*(enc->offset) = '\0';
		}

		len = enc->offset - cLabel + 1;
		ret[i] = PyObject_Malloc(sizeof(char)*len);

		if (!ret[i])
		{
			PyErr_NoMemory();
			ret = 0;
			break;
		}

		memcpy(ret[i], cLabel, sizeof(char)*len);
		dataptr += stride;
	}

	enc->start = origst;
	enc->end = origend;
	enc->offset = origoffset;

	return ret;
}

void Object_beginTypeContext (JSOBJ _obj, JSONTypeContext *tc)
{
	PRINTMARK();
	if (!_obj) {
		tc->type = JT_INVALID;
		return;
	}

	PyObject* obj = (PyObject*) _obj;
	TypeContext *pc = (TypeContext *) tc->prv;
	PyObjectEncoder* enc = (PyObjectEncoder*) tc->encoder;
	PyObject *toDictFunc;

	int i;
	for (i = 0; i < 32; i++) 
	{
		tc->prv[i] = 0;
	}

	if (PyIter_Check(obj) || PyArray_Check(obj))
	{
		goto ISITERABLE;
	}

	if (PyBool_Check(obj))
	{
		PRINTMARK();
		tc->type = (obj == Py_True) ? JT_TRUE : JT_FALSE;
		return;
	}
	else
	if (PyInt_Check(obj))
	{
		PRINTMARK();
#ifdef _LP64
		pc->PyTypeToJSON = PyIntToINT64; tc->type = JT_LONG;
#else
		pc->PyTypeToJSON = PyIntToINT32; tc->type = JT_INT;
#endif
		return;
	}
	else 
	if (PyLong_Check(obj))
	{
		PyObject *exc;

		PRINTMARK();
		pc->PyTypeToJSON = PyLongToINT64; 
		tc->type = JT_LONG;
		GET_TC(tc)->longValue = PyLong_AsLongLong(obj);

		exc = PyErr_Occurred();

		if (exc && PyErr_ExceptionMatches(PyExc_OverflowError))
		{
			PRINTMARK();
			tc->type = JT_INVALID;
			return;
		}

		return;
	}
	else 
	if (PyArray_IsScalar(obj, Integer))
	{
		PyObject *exc;

		PRINTMARK();
		pc->PyTypeToJSON = PyLongToINT64; 
		tc->type = JT_LONG;
		PyArray_CastScalarToCtype(obj, &(GET_TC(tc)->longValue), PyArray_DescrFromType(NPY_LONG));

		exc = PyErr_Occurred();

		if (exc && PyErr_ExceptionMatches(PyExc_OverflowError))
		{
			PRINTMARK();
			tc->type = JT_INVALID;
			return;
		}

		return;
	}
	else
	if (PyString_Check(obj))
	{
		PRINTMARK();
		pc->PyTypeToJSON = PyStringToUTF8; tc->type = JT_UTF8;
		return;
	}
	else
	if (PyUnicode_Check(obj))
	{
		PRINTMARK();
		pc->PyTypeToJSON = PyUnicodeToUTF8; tc->type = JT_UTF8;
		return;
	}
	else
	if (PyFloat_Check(obj))
	{
		PRINTMARK();
		double val = PyFloat_AS_DOUBLE (obj);
		if (npy_isnan(val) || npy_isinf(val))
		{
			tc->type = JT_NULL;
		}
		else 
		{
			pc->PyTypeToJSON = PyFloatToDOUBLE; tc->type = JT_DOUBLE;
		}
		return;
	}
	else
	if (PyArray_IsScalar(obj, Float))
	{
		PRINTMARK();
		pc->PyTypeToJSON = NpyFloatToDOUBLE; tc->type = JT_DOUBLE;
		return;
	}
	else
	if (PyArray_IsScalar(obj, Half))
	{
		PRINTMARK();
		pc->PyTypeToJSON = NpyHalfToDOUBLE; tc->type = JT_DOUBLE;
		return;
	}
	else 
	if (PyArray_IsScalar(obj, Datetime))
	{
		PRINTMARK();
		pc->PyTypeToJSON = NpyDateTimeToINT64; tc->type = JT_LONG;
		return;
	}
	else 
	if (PyDateTime_Check(obj))
	{
		PRINTMARK();
		pc->PyTypeToJSON = PyDateTimeToINT64; tc->type = JT_LONG;
		return;
	}
	else 
	if (PyDate_Check(obj))
	{
		PRINTMARK();
		pc->PyTypeToJSON = PyDateToINT64; tc->type = JT_LONG;
		return;
	}
	else
	if (obj == Py_None)
	{
		PRINTMARK();
		tc->type = JT_NULL;
		return;
	}


ISITERABLE:

	if (PyDict_Check(obj))
	{
		PRINTMARK();
		tc->type = JT_OBJECT;
		pc->iterBegin = Dict_iterBegin;
		pc->iterEnd = Dict_iterEnd;
		pc->iterNext = Dict_iterNext;
		pc->iterGetValue = Dict_iterGetValue;
		pc->iterGetName = Dict_iterGetName;
		pc->dictObj = obj;
		Py_INCREF(obj);

		return;
	}
	else
	if (PyList_Check(obj))
	{
		PRINTMARK();
		tc->type = JT_ARRAY;
		pc->iterBegin = List_iterBegin;
		pc->iterEnd = List_iterEnd;
		pc->iterNext = List_iterNext;
		pc->iterGetValue = List_iterGetValue;
		pc->iterGetName = List_iterGetName;
		return;
	}
	else
	if (PyTuple_Check(obj))
	{
		PRINTMARK();
		tc->type = JT_ARRAY;
		pc->iterBegin = Tuple_iterBegin;
		pc->iterEnd = Tuple_iterEnd;
		pc->iterNext = Tuple_iterNext;
		pc->iterGetValue = Tuple_iterGetValue;
		pc->iterGetName = Tuple_iterGetName;
		return;
	}
	else
	if (PyObject_TypeCheck(obj, (PyTypeObject*) cls_index))
	{
		if (enc->outputFormat == SPLIT) 
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->iterBegin = Index_iterBegin;
			pc->iterEnd = Index_iterEnd;
			pc->iterNext = Index_iterNext;
			pc->iterGetValue = Index_iterGetValue;
			pc->iterGetName = Index_iterGetName;
			return;
		}

		PRINTMARK();
		tc->type = JT_ARRAY;
		pc->newObj = PyObject_GetAttrString(obj, "values");
		pc->iterBegin = NpyArr_iterBegin;
		pc->iterEnd = NpyArr_iterEnd;
		pc->iterNext = NpyArr_iterNext;
		pc->iterGetValue = NpyArr_iterGetValue;
		pc->iterGetName = NpyArr_iterGetName;
		return;
	}
	else
	if (PyObject_TypeCheck(obj, (PyTypeObject*) cls_series))
	{
		if (enc->outputFormat == SPLIT) 
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->iterBegin = Series_iterBegin;
			pc->iterEnd = Series_iterEnd;
			pc->iterNext = Series_iterNext;
			pc->iterGetValue = Series_iterGetValue;
			pc->iterGetName = Series_iterGetName;
			return;
		}

		if (enc->outputFormat == INDEX || enc->outputFormat == COLUMNS)
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->columnLabelsLen = PyArray_SIZE(obj);
			pc->columnLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "index"), (JSONObjectEncoder*) enc, pc->columnLabelsLen);
			if (!pc->columnLabels)
			{
				tc->type = JT_INVALID;
				return;
			}
		}
		else
		{
			PRINTMARK();
			tc->type = JT_ARRAY;
		}
		pc->newObj = PyObject_GetAttrString(obj, "values");
		pc->iterBegin = NpyArr_iterBegin;
		pc->iterEnd = NpyArr_iterEnd;
		pc->iterNext = NpyArr_iterNext;
		pc->iterGetValue = NpyArr_iterGetValue;
		pc->iterGetName = NpyArr_iterGetName;
		return;
	}
	else
	if (PyArray_Check(obj))
	{
		if (enc->npyCtxtPassthru)
		{
			PRINTMARK();
			pc->npyarr = enc->npyCtxtPassthru;
			tc->type = (pc->npyarr->columnLabels ? JT_OBJECT : JT_ARRAY);
			pc->iterBegin = NpyArrPassThru_iterBegin;
			pc->iterEnd = NpyArrPassThru_iterEnd;
			pc->iterNext = NpyArr_iterNext;
			pc->iterGetValue = NpyArr_iterGetValue;
			pc->iterGetName = NpyArr_iterGetName;
			enc->npyCtxtPassthru = NULL;
			return;
		}

		PRINTMARK();
		tc->type = JT_ARRAY;
		pc->iterBegin = NpyArr_iterBegin;
		pc->iterEnd = NpyArr_iterEnd;
		pc->iterNext = NpyArr_iterNext;
		pc->iterGetValue = NpyArr_iterGetValue;
		pc->iterGetName = NpyArr_iterGetName;
		return;
	}
	else
	if (PyObject_TypeCheck(obj, (PyTypeObject*) cls_dataframe))
	{
		if (enc->outputFormat == SPLIT) 
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->iterBegin = DataFrame_iterBegin;
			pc->iterEnd = DataFrame_iterEnd;
			pc->iterNext = DataFrame_iterNext;
			pc->iterGetValue = DataFrame_iterGetValue;
			pc->iterGetName = DataFrame_iterGetName;
			return;
		}

		PRINTMARK();
		pc->newObj = PyObject_GetAttrString(obj, "values");
		pc->iterBegin = NpyArr_iterBegin;
		pc->iterEnd = NpyArr_iterEnd;
		pc->iterNext = NpyArr_iterNext;
		pc->iterGetValue = NpyArr_iterGetValue;
		pc->iterGetName = NpyArr_iterGetName;
		if (enc->outputFormat == VALUES)
		{
			PRINTMARK();
			tc->type = JT_ARRAY;
		}
		else
		if (enc->outputFormat == RECORDS)
		{
			PRINTMARK();
			tc->type = JT_ARRAY;
			pc->columnLabelsLen = PyArray_DIM(pc->newObj, 1);
			pc->columnLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "columns"), (JSONObjectEncoder*) enc, pc->columnLabelsLen);
			if (!pc->columnLabels)
			{
				tc->type = JT_INVALID;
				return;
			}
		}
		else 
		if (enc->outputFormat == INDEX)
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->rowLabelsLen = PyArray_DIM(pc->newObj, 0);
			pc->rowLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "index"), (JSONObjectEncoder*) enc, pc->rowLabelsLen);
			if (!pc->rowLabels)
			{
				tc->type = JT_INVALID;
				return;
			}
			pc->columnLabelsLen = PyArray_DIM(pc->newObj, 1);
			pc->columnLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "columns"), (JSONObjectEncoder*) enc, pc->columnLabelsLen);
			if (!pc->columnLabels)
			{
				NpyArr_freeLabels(pc->rowLabels, pc->rowLabelsLen);
				pc->rowLabels = NULL;
				tc->type = JT_INVALID;
				return;
			}
		}
		else 
		{
			PRINTMARK();
			tc->type = JT_OBJECT;
			pc->rowLabelsLen = PyArray_DIM(pc->newObj, 1);
			pc->rowLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "columns"), (JSONObjectEncoder*) enc, pc->rowLabelsLen);
			if (!pc->rowLabels)
			{
				tc->type = JT_INVALID;
				return;
			}
			pc->columnLabelsLen = PyArray_DIM(pc->newObj, 0);
			pc->columnLabels = NpyArr_encodeLabels((PyArrayObject*) PyObject_GetAttrString(obj, "index"), (JSONObjectEncoder*) enc, pc->columnLabelsLen);
			if (!pc->columnLabels)
			{
				NpyArr_freeLabels(pc->rowLabels, pc->rowLabelsLen);
				pc->rowLabels = NULL;
				tc->type = JT_INVALID;
				return;
			}
			pc->transpose = 1;
		}
		return;
	}


	toDictFunc = PyObject_GetAttrString(obj, "toDict");

	if (toDictFunc)
	{
		PyObject* tuple = PyTuple_New(0);
		PyObject* toDictResult = PyObject_Call(toDictFunc, tuple, NULL);
		Py_DECREF(tuple);
		Py_DECREF(toDictFunc);

		if (toDictResult == NULL)
		{
			PyErr_Clear();
			tc->type = JT_NULL;
			return;
		}

		if (!PyDict_Check(toDictResult))
		{
			Py_DECREF(toDictResult);
			tc->type = JT_NULL;
			return;
		}

		PRINTMARK();
		tc->type = JT_OBJECT;
		pc->iterBegin = Dict_iterBegin;
		pc->iterEnd = Dict_iterEnd;
		pc->iterNext = Dict_iterNext;
		pc->iterGetValue = Dict_iterGetValue;
		pc->iterGetName = Dict_iterGetName;
		pc->dictObj = toDictResult;
		return;
	}

	PyErr_Clear();

	tc->type = JT_OBJECT;
	pc->iterBegin = Dir_iterBegin;
	pc->iterEnd = Dir_iterEnd;
	pc->iterNext = Dir_iterNext;
	pc->iterGetValue = Dir_iterGetValue;
	pc->iterGetName = Dir_iterGetName;

	return;
}


void Object_endTypeContext(JSOBJ obj, JSONTypeContext *tc)
{
	Py_XDECREF(GET_TC(tc)->newObj);
	NpyArr_freeLabels(GET_TC(tc)->rowLabels, GET_TC(tc)->rowLabelsLen);
	NpyArr_freeLabels(GET_TC(tc)->columnLabels, GET_TC(tc)->columnLabelsLen);
}

const char *Object_getStringValue(JSOBJ obj, JSONTypeContext *tc, size_t *_outLen)
{
	return GET_TC(tc)->PyTypeToJSON (obj, tc, NULL, _outLen);
}

JSINT64 Object_getLongValue(JSOBJ obj, JSONTypeContext *tc)
{
	JSINT64 ret;
	GET_TC(tc)->PyTypeToJSON (obj, tc, &ret, NULL);

	return ret;
}

JSINT32 Object_getIntValue(JSOBJ obj, JSONTypeContext *tc)
{
	JSINT32 ret;
	GET_TC(tc)->PyTypeToJSON (obj, tc, &ret, NULL);
	return ret;
}


double Object_getDoubleValue(JSOBJ obj, JSONTypeContext *tc)
{
	double ret;
	GET_TC(tc)->PyTypeToJSON (obj, tc, &ret, NULL);
	return ret;
}

static void Object_releaseObject(JSOBJ _obj)
{
	Py_DECREF( (PyObject *) _obj);
}



void Object_iterBegin(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->iterBegin(obj, tc);
}

int Object_iterNext(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->iterNext(obj, tc);
}

void Object_iterEnd(JSOBJ obj, JSONTypeContext *tc)
{
	GET_TC(tc)->iterEnd(obj, tc);
}

JSOBJ Object_iterGetValue(JSOBJ obj, JSONTypeContext *tc)
{
	return GET_TC(tc)->iterGetValue(obj, tc);
}

char *Object_iterGetName(JSOBJ obj, JSONTypeContext *tc, size_t *outLen)
{
	return GET_TC(tc)->iterGetName(obj, tc, outLen);
}


PyObject* objToJSON(PyObject* self, PyObject *args, PyObject *kwargs)
{
	static char *kwlist[] = { "obj", "ensure_ascii", "double_precision", "orient", NULL};

	char buffer[65536];
	char *ret;
	PyObject *newobj;
	PyObject *oinput = NULL;
	PyObject *oensureAscii = NULL;
	char *sOrient = NULL;
	int idoublePrecision = 5; // default double precision setting

	PyObjectEncoder pyEncoder = 
	{
		{
			Object_beginTypeContext,	//void (*beginTypeContext)(JSOBJ obj, JSONTypeContext *tc);
			Object_endTypeContext, //void (*endTypeContext)(JSOBJ obj, JSONTypeContext *tc);
			Object_getStringValue, //const char *(*getStringValue)(JSOBJ obj, JSONTypeContext *tc, size_t *_outLen);
			Object_getLongValue, //JSLONG (*getLongValue)(JSOBJ obj, JSONTypeContext *tc);
			Object_getIntValue, //JSLONG (*getLongValue)(JSOBJ obj, JSONTypeContext *tc);
			Object_getDoubleValue, //double (*getDoubleValue)(JSOBJ obj, JSONTypeContext *tc);
			Object_iterBegin, //JSPFN_ITERBEGIN iterBegin;
			Object_iterNext, //JSPFN_ITERNEXT iterNext;
			Object_iterEnd, //JSPFN_ITEREND iterEnd;
			Object_iterGetValue, //JSPFN_ITERGETVALUE iterGetValue;
			Object_iterGetName, //JSPFN_ITERGETNAME iterGetName;
			Object_releaseObject, //void (*releaseValue)(JSONTypeContext *ti);
			PyObject_Malloc, //JSPFN_MALLOC malloc;
			PyObject_Realloc, //JSPFN_REALLOC realloc;
			PyObject_Free, //JSPFN_FREE free;
			-1, //recursionMax
			idoublePrecision,
			1, //forceAscii
		}
	};
	JSONObjectEncoder* encoder = (JSONObjectEncoder*) &pyEncoder;

	pyEncoder.npyCtxtPassthru = NULL;
	pyEncoder.outputFormat = COLUMNS;

	PRINTMARK();

	if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|Ois", kwlist, &oinput, &oensureAscii, &idoublePrecision, &sOrient))
	{
		return NULL;
	}

	if (sOrient != NULL)
	{
		if (strcmp(sOrient, "records") == 0)
		{
			pyEncoder.outputFormat = RECORDS;
		} 
		else
		if (strcmp(sOrient, "index") == 0)
		{
			pyEncoder.outputFormat = INDEX;
		}
		else
		if (strcmp(sOrient, "split") == 0)
		{
			pyEncoder.outputFormat = SPLIT;
		}
		else
		if (strcmp(sOrient, "values") == 0)
		{
			pyEncoder.outputFormat = VALUES;
		}
		else
		if (strcmp(sOrient, "columns") != 0)
		{
			PyErr_Format (PyExc_ValueError, "Invalid value '%s' for option 'orient'", sOrient);
			return NULL;
		}
	}

	pyEncoder.originalOutputFormat = pyEncoder.outputFormat;

	if (oensureAscii != NULL && !PyObject_IsTrue(oensureAscii))
	{
		encoder->forceASCII = 0;
	}

	encoder->doublePrecision = idoublePrecision;

	PRINTMARK();
	ret = JSON_EncodeObject (oinput, encoder, buffer, sizeof (buffer));
	PRINTMARK();

	if (PyErr_Occurred())
	{
		return NULL;
	}

	if (encoder->errorMsg)
	{
		if (ret != buffer)
		{
			encoder->free (ret);
		}

		PyErr_Format (PyExc_OverflowError, "%s", encoder->errorMsg);
		return NULL;
	}

	newobj = PyString_FromString (ret);

	if (ret != buffer)
	{
		encoder->free (ret);
	}

	PRINTMARK();

	return newobj;
}

PyObject* objToJSONFile(PyObject* self, PyObject *args, PyObject *kwargs)
{
	PyObject *data;
	PyObject *file;
	PyObject *string;
	PyObject *write;
	PyObject *argtuple;

	PRINTMARK();

	if (!PyArg_ParseTuple (args, "OO", &data, &file)) {
		return NULL;
	}

	if (!PyObject_HasAttrString (file, "write"))
	{
		PyErr_Format (PyExc_TypeError, "expected file");
		return NULL;
	}

	write = PyObject_GetAttrString (file, "write");

	if (!PyCallable_Check (write)) {
		Py_XDECREF(write);
		PyErr_Format (PyExc_TypeError, "expected file");
		return NULL;
	}

	argtuple = PyTuple_Pack(1, data);

	string = objToJSON (self, argtuple, kwargs);

	if (string == NULL)
	{
		Py_XDECREF(write);
		Py_XDECREF(argtuple);
		return NULL;
	}

	Py_XDECREF(argtuple);

	argtuple = PyTuple_Pack (1, string);
	if (argtuple == NULL)
	{
		Py_XDECREF(write);
		return NULL;
	}
	if (PyObject_CallObject (write, argtuple) == NULL)
	{
		Py_XDECREF(write);
		Py_XDECREF(argtuple);
		return NULL;
	}

	Py_XDECREF(write);
	Py_DECREF(argtuple);
	Py_XDECREF(string);

	PRINTMARK();

	Py_RETURN_NONE;
	

}

