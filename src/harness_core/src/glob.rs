use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::path::Path;

#[pyfunction]
pub fn rust_glob(
    py: Python<'_>,
    root_dir: &str,
    pattern: &str,
    max_results: usize,
) -> PyResult<Vec<String>> {
    py.detach(move || {
        let root = Path::new(root_dir);
        if !root.exists() {
            return Err(PyValueError::new_err(format!("Path not found: {root_dir}")));
        }

        let matcher = globset::Glob::new(pattern)
            .map_err(|err| PyValueError::new_err(format!("Invalid glob pattern: {err}")))?
            .compile_matcher();

        let mut matches: Vec<String> = Vec::new();

        for entry in ignore::WalkBuilder::new(root).build() {
            if matches.len() >= max_results {
                break;
            }

            let Ok(entry) = entry else {
                continue;
            };

            let path = entry.path();
            if !path.is_file() {
                continue;
            }

            let rel = match path.strip_prefix(root).ok().and_then(Path::to_str) {
                Some(v) => v,
                None => continue,
            };

            if matcher.is_match(rel) {
                matches.push(rel.to_string());
            }
        }

        matches.sort();
        Ok(matches)
    })
}
