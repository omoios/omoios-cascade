use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyList, PyNone, PyString};

fn json_value_to_py(py: Python<'_>, val: &serde_json::Value) -> PyResult<Py<PyAny>> {
    match val {
        serde_json::Value::Null => {
            Ok(PyNone::get(py).to_owned().into_any().unbind())
        }
        serde_json::Value::Bool(b) => {
            Ok(PyBool::new(py, *b).to_owned().into_any().unbind())
        }
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_pyobject(py)?.into_any().unbind())
            } else if let Some(f) = n.as_f64() {
                Ok(PyFloat::new(py, f).into_any().unbind())
            } else {
                Err(PyValueError::new_err("Unsupported number type"))
            }
        }
        serde_json::Value::String(s) => {
            Ok(PyString::new(py, s).into_any().unbind())
        }
        serde_json::Value::Array(arr) => {
            let items: Vec<Py<PyAny>> = arr
                .iter()
                .map(|v| json_value_to_py(py, v))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(PyList::new(py, &items)?.into_any().unbind())
        }
        serde_json::Value::Object(map) => {
            let dict = PyDict::new(py);
            for (k, v) in map {
                dict.set_item(k, json_value_to_py(py, v)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

fn py_to_json_value(obj: &Bound<'_, PyAny>) -> PyResult<serde_json::Value> {
    if obj.is_none() {
        Ok(serde_json::Value::Null)
    } else if let Ok(b) = obj.extract::<bool>() {
        Ok(serde_json::Value::Bool(b))
    } else if let Ok(i) = obj.extract::<i64>() {
        Ok(serde_json::Value::Number(serde_json::Number::from(i)))
    } else if let Ok(f) = obj.extract::<f64>() {
        Ok(serde_json::Number::from_f64(f)
            .map(serde_json::Value::Number)
            .unwrap_or(serde_json::Value::Null))
    } else if let Ok(s) = obj.extract::<String>() {
        Ok(serde_json::Value::String(s))
    } else if let Ok(list) = obj.cast::<PyList>() {
        let items: Vec<serde_json::Value> = list
            .iter()
            .map(|item| py_to_json_value(&item))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(serde_json::Value::Array(items))
    } else if let Ok(dict) = obj.cast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k, v) in dict {
            let key = k.extract::<String>()?;
            map.insert(key, py_to_json_value(&v)?);
        }
        Ok(serde_json::Value::Object(map))
    } else {
        let repr = obj.repr()?.to_string();
        Ok(serde_json::Value::String(repr))
    }
}

#[pyfunction]
pub fn rust_parse_json(py: Python<'_>, json_str: &str) -> PyResult<Py<PyAny>> {
    let val: serde_json::Value = serde_json::from_str(json_str)
        .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
    json_value_to_py(py, &val)
}

#[pyfunction]
pub fn rust_serialize_json(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let val = py_to_json_value(obj)?;
    serde_json::to_string(&val)
        .map_err(|e| PyValueError::new_err(format!("JSON serialize error: {e}")))
}

#[pyfunction]
pub fn rust_serialize_json_pretty(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let val = py_to_json_value(obj)?;
    serde_json::to_string_pretty(&val)
        .map_err(|e| PyValueError::new_err(format!("JSON serialize error: {e}")))
}
