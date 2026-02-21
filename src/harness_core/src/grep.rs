use grep_regex::RegexMatcher;
use grep_searcher::{Searcher, SearcherBuilder, Sink, SinkMatch};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::io;
use std::path::{Path, PathBuf};

struct CollectSink {
    matches: Vec<(String, usize, String)>,
    relative_path: String,
    max_results: usize,
}

impl Sink for CollectSink {
    type Error = io::Error;

    fn matched(&mut self, _searcher: &Searcher, mat: &SinkMatch<'_>) -> Result<bool, Self::Error> {
        if self.matches.len() >= self.max_results {
            return Ok(false);
        }

        let line_number = mat.line_number().map_or(0, |n| n as usize);
        let line_content = String::from_utf8_lossy(mat.bytes())
            .trim_end_matches('\n')
            .trim_end_matches('\r')
            .to_string();

        self.matches
            .push((self.relative_path.clone(), line_number, line_content));

        Ok(self.matches.len() < self.max_results)
    }
}

#[pyfunction]
pub fn rust_grep(
    py: Python<'_>,
    root_dir: &str,
    pattern: &str,
    file_glob: Option<&str>,
    max_results: usize,
) -> PyResult<Vec<(String, usize, String)>> {
    py.detach(move || {
        let root = PathBuf::from(root_dir);
        let metadata = std::fs::metadata(&root)
            .map_err(|err| PyValueError::new_err(format!("Invalid root path: {err}")))?;

        let matcher = RegexMatcher::new(pattern)
            .map_err(|err| PyValueError::new_err(format!("Invalid regex pattern: {err}")))?;
        let mut searcher = SearcherBuilder::new().line_number(true).build();
        let glob_matcher = if let Some(glob) = file_glob {
            Some(
                globset::Glob::new(glob)
                    .map_err(|err| PyValueError::new_err(format!("Invalid glob pattern: {err}")))?
                    .compile_matcher(),
            )
        } else {
            None
        };

        let mut out: Vec<(String, usize, String)> = Vec::new();

        if metadata.is_file() {
            let rel = root
                .file_name()
                .and_then(|s| s.to_str())
                .ok_or_else(|| PyValueError::new_err("Invalid file name"))?
                .to_string();

            if glob_matcher.as_ref().is_none_or(|m| m.is_match(&rel)) {
                let mut sink = CollectSink {
                    matches: Vec::new(),
                    relative_path: rel,
                    max_results,
                };
                searcher
                    .search_path(&matcher, &root, &mut sink)
                    .map_err(|err| PyValueError::new_err(format!("grep search failed: {err}")))?;
                out.extend(sink.matches);
            }
            return Ok(out);
        }

        for entry in ignore::WalkBuilder::new(&root)
            .hidden(false)
            .ignore(false)
            .git_ignore(false)
            .git_global(false)
            .git_exclude(false)
            .build()
        {
            if out.len() >= max_results {
                break;
            }

            let Ok(entry) = entry else {
                continue;
            };
            let path = entry.path();
            if !path.is_file() {
                continue;
            }

            let rel = match path.strip_prefix(&root).ok().and_then(Path::to_str) {
                Some(v) => v.to_string(),
                None => continue,
            };

            if !glob_matcher.as_ref().is_none_or(|m| m.is_match(&rel)) {
                continue;
            }

            let remaining = max_results.saturating_sub(out.len());
            if remaining == 0 {
                break;
            }

            let mut sink = CollectSink {
                matches: Vec::new(),
                relative_path: rel,
                max_results: remaining,
            };
            searcher
                .search_path(&matcher, path, &mut sink)
                .map_err(|err| PyValueError::new_err(format!("grep search failed: {err}")))?;
            out.extend(sink.matches);
        }

        Ok(out)
    })
}
