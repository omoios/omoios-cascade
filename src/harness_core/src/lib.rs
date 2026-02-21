mod diff;
mod snapshot;

use pyo3::prelude::*;

#[pymodule]
fn harness_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(snapshot::snapshot_workspace, m)?)?;
    m.add_function(wrap_pyfunction!(diff::compute_diff, m)?)?;
    Ok(())
}
