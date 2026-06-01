use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow};

use crate::loop0::config::{Loop0RunConfig, resolve_path};

pub fn load_env(config: &Loop0RunConfig) -> Result<BTreeMap<String, String>> {
    let mut values = BTreeMap::new();
    for path in env_paths(config)? {
        if !path.exists() {
            continue;
        }
        values.extend(read_dotenv(&path)?);
    }
    values.extend(std::env::vars());
    Ok(values)
}

fn env_paths(config: &Loop0RunConfig) -> Result<Vec<PathBuf>> {
    if let Some(path) = &config.env_file {
        return Ok(vec![resolve_path(&config.base_dir, path)]);
    }
    let cwd = std::env::current_dir().context("failed to read current directory")?;
    let cwd_env = cwd.join(".env");
    let config_env = config.base_dir.join(".env");
    if cwd_env == config_env {
        Ok(vec![cwd_env])
    } else {
        Ok(vec![cwd_env, config_env])
    }
}

pub fn read_dotenv(path: &Path) -> Result<BTreeMap<String, String>> {
    let text = fs::read_to_string(path)
        .with_context(|| format!("failed to read env file {}", path.display()))?;
    let mut values = BTreeMap::new();
    for (index, raw_line) in text.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line).trim();
        let Some((key, value)) = line.split_once('=') else {
            return Err(anyhow!(
                "invalid env line in {}:{}: expected KEY=VALUE",
                path.display(),
                index + 1
            ));
        };
        let key = key.trim();
        if key.is_empty() {
            return Err(anyhow!(
                "invalid env line in {}:{}: empty key",
                path.display(),
                index + 1
            ));
        }
        values.insert(key.to_string(), strip_env_value(value.trim()));
    }
    Ok(values)
}

fn strip_env_value(value: &str) -> String {
    if value.len() >= 2 {
        let bytes = value.as_bytes();
        if (bytes[0] == b'\'' && bytes[value.len() - 1] == b'\'')
            || (bytes[0] == b'"' && bytes[value.len() - 1] == b'"')
        {
            return value[1..value.len() - 1].to_string();
        }
    }
    value.to_string()
}
