use blake3::Hasher;
use pyo3::prelude::*;
use rayon::prelude::*;
use std::path::PathBuf;

#[pyfunction]
pub fn rust_hash_files(py: Python<'_>, paths: Vec<String>) -> Vec<(String, String)> {
    py.detach(move || {
        paths
            .par_iter()
            .map(|path| {
                let p = PathBuf::from(path);
                match std::fs::read(&p) {
                    Ok(data) => {
                        let mut hasher = Hasher::new();
                        hasher.update(&data);
                        let hash = hasher.finalize();
                        (path.clone(), hash.to_hex().to_string())
                    }
                    Err(_) => (path.clone(), String::new()),
                }
            })
            .collect()
    })
}

#[pyfunction]
pub fn rust_hash_bytes(py: Python<'_>, data: &[u8]) -> String {
    py.detach(move || {
        let mut hasher = Hasher::new();
        hasher.update(data);
        hasher.finalize().to_hex().to_string()
    })
}
