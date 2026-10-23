// The PotluckDB release this crate links, written by rust/scripts/set_version.py.
// In a release (git tag rust-v<version>) it also lists the SHA-256 of each
// platform's archive, so that the build accepts only those exact files;
// without them it checks the release's SHA256SUMS.
const POTLUCKDB_VERSION: &str = "0.8.0-dev.0";
const POTLUCKDB_SHA256: &[(&str, &str)] = &[];
