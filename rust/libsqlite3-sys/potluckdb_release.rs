// The PotluckDB release this crate links, written by rust/scripts/set_version.py.
// In a release (git tag rust-v<version>) it also lists the SHA-256 of each
// platform's archive, so that the build accepts only those exact files;
// without them it checks the release's SHA256SUMS.
const POTLUCKDB_VERSION: &str = "0.8.0-dev.2";
const POTLUCKDB_SHA256: &[(&str, &str)] = &[
    ("linux-x64-gnu", "2478036f05f5f84d455367ecd07e10e5e3b19fb483964c4c2afa9e9348100f5b"),
    ("linux-arm64-gnu", "da31e0421c5f8937a41388326b9b34edff1291db24dabf7a3670dd327345442f"),
    ("linux-x64-musl", "d34860755b5cb30b3202a91378ba26d41b3b4c44e1fee8ef2cd4acfcf0f273a8"),
    ("linux-arm64-musl", "0e346ccf7325a800be5d15ebc869d0cc4925e8b8c63b03f6dee192f6742cd8c4"),
    ("macos-arm64", "797b5eeb33c31425c93e137ca6e0c0046eb8c4eb7ecafd9431cfa481e8e5dd92"),
    ("macos-x64", "9742e7d1c6463eb962a9a262be88fddb3bb05c7a4ddef8b2925f3e12438184a6"),
    ("windows-x64", "79ff3f69712442530f3f1c622d6fe1543d14c3874e53e118d76677f72a87caca"),
    ("windows-arm64", "974c6d0fe4c23a8f62634a3f724f509b5121e5ed86b575a64ccaec887def7b31"),
];
