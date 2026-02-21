mod aho;
mod diff;
mod glob;
mod grep;
mod hash;
mod json_ops;
mod read;
mod shell;
mod snapshot;

use pyo3::prelude::*;

#[pymodule]
fn harness_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(snapshot::snapshot_workspace, m)?)?;
    m.add_function(wrap_pyfunction!(diff::compute_diff, m)?)?;
    m.add_function(wrap_pyfunction!(grep::rust_grep, m)?)?;
    m.add_function(wrap_pyfunction!(glob::rust_glob, m)?)?;
    m.add_function(wrap_pyfunction!(hash::rust_hash_files, m)?)?;
    m.add_function(wrap_pyfunction!(hash::rust_hash_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(json_ops::rust_parse_json, m)?)?;
    m.add_function(wrap_pyfunction!(json_ops::rust_serialize_json, m)?)?;
    m.add_function(wrap_pyfunction!(json_ops::rust_serialize_json_pretty, m)?)?;
    m.add_function(wrap_pyfunction!(aho::rust_multi_grep, m)?)?;
    m.add_function(wrap_pyfunction!(aho::rust_multi_grep_lines, m)?)?;
    m.add_function(wrap_pyfunction!(read::rust_read_files, m)?)?;
    m.add_function(wrap_pyfunction!(read::rust_read_files_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(shell::rust_run_command, m)?)?;
    Ok(())
}
