// The library linked into the test binary is PotluckDB's, through the C API.
use std::ffi::{CStr, CString};
use std::ptr;

#[test]
fn versions() {
    assert_eq!(potluckdb::version(), potluckdb::VERSION);
    assert!(potluckdb::sqlite_version().starts_with("3."), "{}", potluckdb::sqlite_version());
}

#[test]
fn query_through_the_c_api() {
    use potluckdb::ffi;
    unsafe {
        let mut db = ptr::null_mut();
        let name = CString::new(":memory:").unwrap();
        assert_eq!(ffi::sqlite3_open(name.as_ptr(), &mut db), ffi::SQLITE_OK);
        let sql = CString::new("SELECT potluckdb_version(), sqlite_version()").unwrap();
        let mut stmt = ptr::null_mut();
        assert_eq!(ffi::sqlite3_prepare_v2(db, sql.as_ptr(), -1, &mut stmt, ptr::null_mut()), ffi::SQLITE_OK);
        assert_eq!(ffi::sqlite3_step(stmt), ffi::SQLITE_ROW);
        let column = |i| CStr::from_ptr(ffi::sqlite3_column_text(stmt, i).cast()).to_str().unwrap().to_owned();
        assert_eq!(column(0), potluckdb::version());
        assert_eq!(column(1), potluckdb::sqlite_version());
        ffi::sqlite3_finalize(stmt);
        ffi::sqlite3_close(db);
    }
}
