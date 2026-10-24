type: added

`potluckdb attach app.db s3://my-bucket/app` makes a database sync without changing any program: it writes `app.db.potluckdb` next to the database, which every program on PotluckDB's library reads. `potluckdb detach app.db` stops it.
