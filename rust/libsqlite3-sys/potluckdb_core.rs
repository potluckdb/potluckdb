// PotluckDB: makes libsqlite3-sys link PotluckDB's build of SQLite.
//
// This file is part of PotluckDB (https://github.com/potluckdb/potluckdb) and
// licensed under Apache-2.0. The rest of this crate is libsqlite3-sys (MIT,
// the rusqlite developers), unchanged except for the end of build.rs, which
// calls `configure()` before libsqlite3-sys's own build logic runs.
//
// `configure()` finds PotluckDB's core archive for the target platform and
// sets the environment variables that libsqlite3-sys reads, so that its own
// code links the archive's static library and uses its headers:
//
//   SQLITE3_LIB_DIR, SQLITE3_INCLUDE_DIR, SQLITE3_STATIC=1
//       link lib/static from the archive, with include/ as the headers
//   LIBSQLITE3_SYS_USE_PKG_CONFIG=1
//       link a library even when the `bundled` feature is on (rusqlite's
//       `bundled`, sqlx's `sqlite`), instead of compiling the bundled SQLite
//   SQLITE3_NO_PKG_CONFIG=1
//       never ask pkg-config, which would find a system SQLite first
//
// Where the archive comes from:
// - POTLUCKDB_CORE_DIR: a folder holding the archives
//   (potluckdb-sqlite-<version>-<platform>.tar.gz or .zip, checked against
//   SHA256SUMS if the folder has one), or one unpacked archive. Nothing is
//   downloaded.
// - Otherwise the GitHub release v<version> of potluckdb/potluckdb (or
//   POTLUCKDB_DOWNLOAD_URL/v<version>/, for a mirror), downloaded with curl
//   into OUT_DIR and checked against the SHA-256 recorded in
//   potluckdb_release.rs, or against the release's SHA256SUMS if none is
//   recorded.
// The version is POTLUCKDB_VERSION in potluckdb_release.rs, unless
// POTLUCKDB_CORE_VERSION says otherwise.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

include!("potluckdb_release.rs");

const DOWNLOAD_URL: &str = "https://github.com/potluckdb/potluckdb/releases/download";
const PLATFORMS: &str = "linux-x64-gnu, linux-arm64-gnu, linux-x64-musl, linux-arm64-musl, \
                         macos-arm64, macos-x64, windows-x64 (MSVC), windows-arm64 (MSVC)";

pub fn configure() {
    for var in ["POTLUCKDB_CORE_DIR", "POTLUCKDB_CORE_VERSION", "POTLUCKDB_DOWNLOAD_URL"] {
        println!("cargo:rerun-if-env-changed={var}");
    }
    if cfg!(any(feature = "loadable_extension", feature = "in_gecko")) {
        // A loadable extension links no SQLite: the program that loads it
        // brings its own. Gecko links SQLite itself.
        return;
    }
    if cfg!(any(feature = "sqlcipher", feature = "bundled-sqlcipher")) {
        fail(
            "the `sqlcipher` and `bundled-sqlcipher` features ask for SQLCipher, which PotluckDB's \
             SQLite does not include. Turn them off, or remove the [patch.crates-io] entry for \
             libsqlite3-sys to keep SQLCipher.",
        );
    }
    for var in ["SQLITE3_LIB_DIR", "SQLITE3_INCLUDE_DIR", "SQLITE3_STATIC", "LIBSQLITE3_SYS_USE_PKG_CONFIG"] {
        if env::var_os(var).is_some() {
            println!(
                "cargo:warning=PotluckDB: {var} is ignored; this libsqlite3-sys always links \
                 PotluckDB's SQLite (POTLUCKDB_CORE_DIR chooses where its files come from)"
            );
        }
    }

    let platform = platform();
    let version = env_value("POTLUCKDB_CORE_VERSION").unwrap_or_else(|| POTLUCKDB_VERSION.to_string());
    let work = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR")).join("potluckdb");
    let core = find_core(&version, &platform, &work);
    check_build_info(&core, &version, &platform);

    let lib_dir = core.join("lib").join("static");
    let include_dir = core.join("include");
    env::set_var("LIBSQLITE3_SYS_USE_PKG_CONFIG", "1");
    env::set_var("SQLITE3_NO_PKG_CONFIG", "1");
    env::set_var("SQLITE3_STATIC", "1");
    env::set_var("SQLITE3_LIB_DIR", &lib_dir);
    env::set_var("SQLITE3_INCLUDE_DIR", &include_dir);
    // For crates that build C code against these headers (DEP_SQLITE3_INCLUDE),
    // and for the potluckdb crate, which checks it is built with this crate
    // (DEP_SQLITE3_POTLUCKDB_VERSION).
    println!("cargo:include={}", include_dir.display());
    println!("cargo:lib_dir={}", lib_dir.display());
    println!("cargo:potluckdb_version={version}");
}

// The PotluckDB platform name of the target, as in the archive names.
fn platform() -> String {
    let var = |name: &str| env::var(name).unwrap_or_default();
    let cpu = match var("CARGO_CFG_TARGET_ARCH").as_str() {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        _ => "",
    };
    let platform = match (var("CARGO_CFG_TARGET_OS").as_str(), var("CARGO_CFG_TARGET_ENV").as_str()) {
        ("linux", "gnu") => format!("linux-{cpu}-gnu"),
        ("linux", "musl") => format!("linux-{cpu}-musl"),
        ("macos", _) => format!("macos-{cpu}"),
        ("windows", "msvc") => format!("windows-{cpu}"),
        _ => String::new(),
    };
    if cpu.is_empty() || platform.is_empty() {
        fail(&format!(
            "PotluckDB has no SQLite library for the target {} yet. Its platforms are: {PLATFORMS}.",
            var("TARGET")
        ));
    }
    platform
}

// Returns the folder of the unpacked core archive.
fn find_core(version: &str, platform: &str, work: &Path) -> PathBuf {
    let name = format!("potluckdb-sqlite-{version}-{platform}");
    let file = format!("{name}.{}", if platform.starts_with("windows") { "zip" } else { "tar.gz" });

    if let Some(dir) = env_value("POTLUCKDB_CORE_DIR").map(PathBuf::from) {
        for unpacked in [dir.clone(), dir.join(&name)] {
            if unpacked.join("include").join("sqlite3.h").is_file() {
                return unpacked;
            }
        }
        let archive = dir.join(&file);
        if !archive.is_file() {
            fail(&format!("POTLUCKDB_CORE_DIR={} has no {file} and no unpacked {name} folder", dir.display()));
        }
        println!("cargo:rerun-if-changed={}", archive.display());
        let actual = sha256_hex(&read(&archive));
        let sums = dir.join("SHA256SUMS");
        if let Some(expected) = recorded_sha256(version, platform) {
            check_sum(&actual, expected, &file, "potluckdb_release.rs");
        } else if sums.is_file() {
            let expected = sum_in(&read_text(&sums), &file, &sums.display().to_string());
            check_sum(&actual, &expected, &file, &sums.display().to_string());
        }
        return extract(&archive, work, &name);
    }

    let base = env_value("POTLUCKDB_DOWNLOAD_URL").unwrap_or_else(|| DOWNLOAD_URL.to_string());
    let base = format!("{}/v{version}", base.trim_end_matches('/'));
    create_dir(work);
    let (expected, source) = match recorded_sha256(version, platform) {
        Some(sum) => (sum.to_string(), "potluckdb_release.rs".to_string()),
        None => {
            let sums = work.join("SHA256SUMS");
            let url = format!("{base}/SHA256SUMS");
            download(&url, &sums);
            (sum_in(&read_text(&sums), &file, &url), url)
        }
    };
    let archive = work.join(&file);
    if !(archive.is_file() && sha256_hex(&read(&archive)) == expected) {
        let part = work.join(format!("{file}.part"));
        download(&format!("{base}/{file}"), &part);
        check_sum(&sha256_hex(&read(&part)), &expected, &file, &source);
        fs::rename(&part, &archive).unwrap_or_else(|e| fail(&format!("cannot rename {}: {e}", part.display())));
    }
    extract(&archive, work, &name)
}

fn recorded_sha256(version: &str, platform: &str) -> Option<&'static str> {
    if version != POTLUCKDB_VERSION {
        return None;
    }
    POTLUCKDB_SHA256.iter().find(|(p, _)| *p == platform).map(|(_, sum)| *sum)
}

fn download(url: &str, to: &Path) {
    let status = Command::new("curl")
        .args(["--fail", "--location", "--silent", "--show-error", "--retry", "3", "--connect-timeout", "30"])
        .arg("--output")
        .arg(to)
        .arg(url)
        .status();
    match status {
        Ok(s) if s.success() => {}
        Ok(_) => fail(&format!(
            "could not download {url}. Without network access, download the archive yourself and \
             set POTLUCKDB_CORE_DIR to its folder."
        )),
        Err(e) => fail(&format!(
            "could not run curl to download {url} ({e}). Install curl, or download the archive \
             yourself and set POTLUCKDB_CORE_DIR to its folder."
        )),
    }
}

// Unpacks the archive into `work` and returns the folder it holds.
fn extract(archive: &Path, work: &Path, name: &str) -> PathBuf {
    let unpacked = work.join(name);
    if unpacked.exists() {
        fs::remove_dir_all(&unpacked).unwrap_or_else(|e| fail(&format!("cannot remove {}: {e}", unpacked.display())));
    }
    create_dir(work);
    let zip = archive.extension().is_some_and(|e| e == "zip");
    let windows_host = env::var("HOST").is_ok_and(|h| h.contains("windows"));
    // bsdtar (macOS, and Windows 10 and later in System32) reads .tar.gz and
    // .zip; GNU tar reads only .tar.gz, so .zip falls back to unzip. On Windows
    // System32's tar comes first: a GNU tar on PATH misreads C:\ paths.
    let tar = if windows_host {
        PathBuf::from(env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into()))
            .join("System32")
            .join("tar.exe")
    } else {
        PathBuf::from("tar")
    };
    let mut commands = vec![Command::new(&tar)];
    commands[0].arg(if zip { "-xf" } else { "-xzf" }).arg(archive).arg("-C").arg(work);
    if zip && !windows_host {
        let mut unzip = Command::new("unzip");
        unzip.arg("-q").arg("-o").arg(archive).arg("-d").arg(work);
        commands.push(unzip);
    }
    for mut command in commands {
        if command.status().is_ok_and(|s| s.success()) && unpacked.join("include").join("sqlite3.h").is_file() {
            return unpacked;
        }
    }
    fail(&format!(
        "could not unpack {} with {}. Unpack it yourself and set POTLUCKDB_CORE_DIR to the folder.",
        archive.display(),
        if zip && !windows_host { "tar or unzip" } else { "tar" }
    ))
}

// Checks that the archive is the one for this version and platform.
fn check_build_info(core: &Path, version: &str, platform: &str) {
    let path = core.join("BUILD-INFO.json");
    let info = read_text(&path);
    let target = json_string(&info, "target");
    let built = json_string(&info, "potluckdb_version");
    if target.as_deref() != Some(platform) || built.as_deref() != Some(version) {
        fail(&format!(
            "{} is for {} {}, not for {platform} {version}",
            core.display(),
            target.unwrap_or_default(),
            built.unwrap_or_default()
        ));
    }
}

// The string value of a top-level key in a small, flat JSON object.
fn json_string(json: &str, key: &str) -> Option<String> {
    let rest = &json[json.find(&format!("\"{key}\""))? + key.len() + 2..];
    let rest = rest.trim_start().strip_prefix(':')?.trim_start().strip_prefix('"')?;
    Some(rest[..rest.find('"')?].to_string())
}

// The SHA-256 that a SHA256SUMS file lists for `file`.
fn sum_in(sums: &str, file: &str, source: &str) -> String {
    for line in sums.lines() {
        let mut parts = line.split_whitespace();
        if let (Some(sum), Some(name)) = (parts.next(), parts.next()) {
            if name.trim_start_matches('*') == file {
                return sum.to_ascii_lowercase();
            }
        }
    }
    fail(&format!("{source} does not list {file}"))
}

fn check_sum(actual: &str, expected: &str, file: &str, source: &str) {
    if actual != expected {
        fail(&format!("{file} does not match the SHA-256 in {source} (got {actual}, expected {expected})"));
    }
}

fn env_value(name: &str) -> Option<String> {
    env::var(name).ok().filter(|v| !v.is_empty())
}

fn read(path: &Path) -> Vec<u8> {
    fs::read(path).unwrap_or_else(|e| fail(&format!("cannot read {}: {e}", path.display())))
}

fn read_text(path: &Path) -> String {
    String::from_utf8_lossy(&read(path)).into_owned()
}

fn create_dir(path: &Path) {
    fs::create_dir_all(path).unwrap_or_else(|e| fail(&format!("cannot create {}: {e}", path.display())));
}

fn fail(message: &str) -> ! {
    eprintln!("error: PotluckDB: {message}");
    std::process::exit(1);
}

// SHA-256 (FIPS 180-4), so that the build script needs no dependencies.
fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
        0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
        0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
        0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] =
        [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    let mut message = data.to_vec();
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for start in (0..message.len()).step_by(64) {
        let block = &message[start..start + 64];
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([block[4 * i], block[4 * i + 1], block[4 * i + 2], block[4 * i + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (x, y) in h.iter_mut().zip([a, b, c, d, e, f, g, hh]) {
            *x = x.wrapping_add(y);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}
