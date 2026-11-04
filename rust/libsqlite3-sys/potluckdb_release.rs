// The PotluckDB release this crate links, written by rust/scripts/set_version.py.
// In a release (git tag rust-v<version>) it also lists the SHA-256 of each
// platform's archive, so that the build accepts only those exact files;
// without them it checks the release's SHA256SUMS.
const POTLUCKDB_VERSION: &str = "0.8.0-dev.4";
const POTLUCKDB_SHA256: &[(&str, &str)] = &[
    ("linux-x64-gnu", "e60d5e50fc0e28af312a480ef2287cbf983ad25c96bc9ddd8887d25bd9a3a562"),
    ("linux-arm64-gnu", "2180d6787a569bf2fae60efd3c0d3450a01d5ff90213847dc96b24b76df836c3"),
    ("linux-x64-musl", "fe624fb7e9f329a9243f51ff561148f4962041eb895b34012e9648b238bd129c"),
    ("linux-arm64-musl", "e9742e55964970ff2bb08758850c440e43451d64736d00f6ccb59c02879a32b4"),
    ("macos-arm64", "9487dda5fa3a8ac363e8108809727ac9123ee674b14e549f41db5f8f71632547"),
    ("macos-x64", "243edd1be96d3613163ba8a4ab62ea31af557ed80e96367538a885818a1a9c45"),
    ("windows-x64", "538d114b89f365e587b4253cf864d80ffa5edcb6d71782672607d99d73d13042"),
    ("windows-arm64", "839026be43b16989f27efddc4283652ec2e81815a6d1ccffdd325c134e55ba84"),
];
