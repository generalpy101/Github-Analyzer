// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::Manager;

struct ServerProcess(Mutex<Option<Child>>);

const SERVER_URL: &str = "http://localhost:5959";

fn find_python() -> Option<String> {
    for cmd in &["python3", "python"] {
        if Command::new(cmd)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return Some(cmd.to_string());
        }
    }
    None
}

fn server_is_running() -> bool {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .ok()
        .and_then(|c| c.get(SERVER_URL).send().ok())
        .is_some()
}

fn wait_for_server(timeout_secs: u64) -> bool {
    for _ in 0..(timeout_secs * 2) {
        if server_is_running() {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

/// Try to find and spawn the sidecar binary (production).
fn try_sidecar() -> Option<Child> {
    let exe = std::env::current_exe().ok()?;
    let exe_dir = exe.parent()?;

    let target = if cfg!(target_os = "macos") {
        "aarch64-apple-darwin"
    } else if cfg!(target_os = "windows") {
        "x86_64-pc-windows-msvc"
    } else {
        "x86_64-unknown-linux-gnu"
    };

    let sidecar_name = format!("github-review-server-{}", target);

    // Check next to the executable
    let sidecar_path = exe_dir.join(&sidecar_name);
    if sidecar_path.exists() {
        println!("Found sidecar at: {:?}", sidecar_path);
        return Command::new(&sidecar_path).spawn().ok();
    }

    // macOS bundle: Resources directory
    let resources_path = exe_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.join("Resources").join(&sidecar_name));
    if let Some(ref path) = resources_path {
        if path.exists() {
            println!("Found sidecar at: {:?}", path);
            return Command::new(path).spawn().ok();
        }
    }

    None
}

/// Fallback: spawn Flask via Python directly (development).
fn try_python_dev() -> Option<Child> {
    let python = find_python()?;
    let exe = std::env::current_exe().ok()?;

    let mut path = exe.clone();
    for _ in 0..5 {
        path.pop();
        let candidate = path.join("app.py");
        if candidate.exists() {
            let working_dir = candidate.parent().unwrap().to_path_buf();
            println!("Dev mode: {} {:?}", python, candidate);
            return Command::new(&python)
                .arg(&candidate)
                .current_dir(&working_dir)
                .spawn()
                .ok();
        }
    }

    None
}

fn main() {
    // Check if server is already running (e.g. started by beforeDevCommand)
    let server: Option<Child> = if server_is_running() {
        println!("Server already running at {}", SERVER_URL);
        None
    } else {
        // Try sidecar first (production), then Python (development)
        let child = try_sidecar()
            .or_else(|| {
                println!("Sidecar not found, falling back to Python...");
                try_python_dev()
            });

        match &child {
            Some(c) => println!("Server started (PID: {})", c.id()),
            None => {
                eprintln!("Could not start server, waiting for external server...");
            }
        }

        child
    };

    // Wait for server to be ready
    if !server_is_running() && !wait_for_server(20) {
        eprintln!("Warning: Server did not respond within 20 seconds");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(ServerProcess(Mutex::new(server)))
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.app_handle().state::<ServerProcess>();
                let mut guard = match state.0.lock() {
                    Ok(g) => g,
                    Err(_) => return,
                };
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                    println!("Server process killed");
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Error while running Tauri application");
}
