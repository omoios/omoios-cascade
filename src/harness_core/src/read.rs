use pyo3::prelude::*;
use rayon::prelude::*;
use std::path::PathBuf;

#[pyfunction]
pub fn rust_read_files(py: Python<'_>, paths: Vec<String>) -> Vec<(String, Option<String>)> {
    py.detach(move || {
        paths
            .par_iter()
            .map(|path| {
                let p = PathBuf::from(path);
                match std::fs::read_to_string(&p) {
                    Ok(content) => (path.clone(), Some(content)),
                    Err(_) => (path.clone(), None),
                }
            })
            .collect()
    })
}

#[pyfunction]
pub fn rust_read_files_bytes(py: Python<'_>, paths: Vec<String>) -> Vec<(String, Option<Vec<u8>>)> {
    py.detach(move || {
        paths
            .par_iter()
            .map(|path| {
                let p = PathBuf::from(path);
                match std::fs::read(&p) {
                    Ok(data) => (path.clone(), Some(data)),
                    Err(_) => (path.clone(), None),
                }
            })
            .collect()
    })
}
