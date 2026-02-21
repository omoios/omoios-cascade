use md5::{Digest, Md5};
use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};

#[pyfunction]
pub fn compute_diff(
    py: Python<'_>,
    old_snapshot: HashMap<String, String>,
    new_snapshot: HashMap<String, String>,
) -> Vec<(String, Option<String>, Option<String>, String)> {
    py.detach(move || {
        let all_paths: HashSet<&String> = old_snapshot.keys().chain(new_snapshot.keys()).collect();
        let mut paths: Vec<&String> = all_paths.into_iter().collect();
        paths.sort();

        paths
            .par_iter()
            .filter_map(|path| {
                let old_val = old_snapshot.get(*path);
                let new_val = new_snapshot.get(*path);

                match (old_val, new_val) {
                    (Some(old), Some(new)) => {
                        let old_hash = hex_md5(old.as_bytes());
                        let new_hash = hex_md5(new.as_bytes());
                        if old_hash != new_hash {
                            Some((
                                (*path).clone(),
                                Some(old_hash),
                                Some(new_hash),
                                format!("--- modified: {}", path),
                            ))
                        } else {
                            None
                        }
                    }
                    (None, Some(content)) => Some((
                        (*path).clone(),
                        None,
                        Some(hex_md5(content.as_bytes())),
                        format!("+++ new file: {}", path),
                    )),
                    (Some(content), None) => Some((
                        (*path).clone(),
                        Some(hex_md5(content.as_bytes())),
                        None,
                        format!("--- deleted: {}", path),
                    )),
                    (None, None) => None,
                }
            })
            .collect()
    })
}

fn hex_md5(data: &[u8]) -> String {
    let mut hasher = Md5::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}
