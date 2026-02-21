use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

const IGNORE_PATTERNS: &[&str] = &[
    ".git",
    ".workspaces",
    ".team",
    ".tasks",
    "node_modules",
    "__pycache__",
];

fn should_ignore(path: &Path) -> bool {
    path.components().any(|c| {
        let s = c.as_os_str().to_str().unwrap_or("");
        IGNORE_PATTERNS.contains(&s)
    })
}

#[pyfunction]
pub fn snapshot_workspace(
    py: Python<'_>,
    workspace_path: String,
) -> PyResult<HashMap<String, String>> {
    py.detach(|| {
        let root = PathBuf::from(&workspace_path);

        let entries: Vec<PathBuf> = WalkDir::new(&root)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_type().is_file())
            .map(|e| e.into_path())
            .filter(|p| {
                let rel = p.strip_prefix(&root).unwrap_or(p);
                !should_ignore(rel)
            })
            .collect();

        let results: Vec<(String, String)> = entries
            .par_iter()
            .filter_map(|path| {
                let rel = path.strip_prefix(&root).ok()?;
                let rel_str = rel.to_str()?.to_string();
                let content = std::fs::read_to_string(path).ok()?;
                Some((rel_str, content))
            })
            .collect();

        let mut map = HashMap::with_capacity(results.len());
        for (k, v) in results {
            map.insert(k, v);
        }
        Ok(map)
    })
}
