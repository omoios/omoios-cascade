use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::process::Command;
use std::time::{Duration, Instant};

#[pyfunction]
pub fn rust_run_command(
    py: Python<'_>,
    cmd: &str,
    cwd: Option<&str>,
    timeout_secs: Option<u64>,
) -> PyResult<(i32, String, String)> {
    py.detach(move || {
        let mut command = Command::new("sh");
        command.arg("-c").arg(cmd);

        if let Some(dir) = cwd {
            command.current_dir(dir);
        }

        command
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());

        let mut child = command
            .spawn()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to spawn command: {e}")))?;

        if let Some(timeout) = timeout_secs {
            let deadline = Instant::now() + Duration::from_secs(timeout);
            loop {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        let stdout = child
                            .stdout
                            .take()
                            .map(|s| std::io::read_to_string(s).unwrap_or_default())
                            .unwrap_or_default();
                        let stderr = child
                            .stderr
                            .take()
                            .map(|s| std::io::read_to_string(s).unwrap_or_default())
                            .unwrap_or_default();
                        return Ok((status.code().unwrap_or(-1), stdout, stderr));
                    }
                    Ok(None) => {
                        if Instant::now() >= deadline {
                            let _ = child.kill();
                            let _ = child.wait();
                            return Err(PyRuntimeError::new_err(format!(
                                "Command timed out after {timeout}s"
                            )));
                        }
                        std::thread::sleep(Duration::from_millis(50));
                    }
                    Err(e) => {
                        return Err(PyRuntimeError::new_err(format!(
                            "Error waiting for command: {e}"
                        )));
                    }
                }
            }
        } else {
            let output = child
                .wait_with_output()
                .map_err(|e| PyRuntimeError::new_err(format!("Failed to wait for command: {e}")))?;
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            Ok((output.status.code().unwrap_or(-1), stdout, stderr))
        }
    })
}
