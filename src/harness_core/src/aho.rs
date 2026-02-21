use aho_corasick::AhoCorasick;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
pub fn rust_multi_grep(
    py: Python<'_>,
    text: &str,
    patterns: Vec<String>,
    max_results: Option<usize>,
) -> PyResult<Vec<(usize, usize, String)>> {
    py.detach(move || {
        let ac = AhoCorasick::new(&patterns)
            .map_err(|e| PyValueError::new_err(format!("Failed to build pattern matcher: {e}")))?;

        let limit = max_results.unwrap_or(usize::MAX);
        let mut results = Vec::new();

        for mat in ac.find_iter(&text) {
            if results.len() >= limit {
                break;
            }
            let pattern_idx = mat.pattern().as_usize();
            let matched = &text[mat.start()..mat.end()];
            results.push((mat.start(), pattern_idx, matched.to_string()));
        }

        Ok(results)
    })
}

#[pyfunction]
pub fn rust_multi_grep_lines(
    py: Python<'_>,
    text: &str,
    patterns: Vec<String>,
    max_results: Option<usize>,
) -> PyResult<Vec<(usize, usize, String)>> {
    py.detach(move || {
        let ac = AhoCorasick::new(&patterns)
            .map_err(|e| PyValueError::new_err(format!("Failed to build pattern matcher: {e}")))?;

        let limit = max_results.unwrap_or(usize::MAX);
        let mut results = Vec::new();
        let mut seen_lines = std::collections::HashSet::new();

        for mat in ac.find_iter(&text) {
            if results.len() >= limit {
                break;
            }

            let line_start = text[..mat.start()].rfind('\n').map_or(0, |p| p + 1);
            if seen_lines.contains(&line_start) {
                continue;
            }
            seen_lines.insert(line_start);

            let line_end = text[mat.start()..]
                .find('\n')
                .map_or(text.len(), |p| mat.start() + p);
            let line_num = text[..mat.start()].matches('\n').count() + 1;
            let line_content = text[line_start..line_end].to_string();
            let pattern_idx = mat.pattern().as_usize();

            results.push((line_num, pattern_idx, line_content));
        }

        Ok(results)
    })
}
