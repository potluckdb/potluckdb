type: added

Databases sync: add `?potluckdb=<bucket>` to a database's address (for example `file:app.db?potluckdb=s3://my-bucket/app`), or put a file `app.db.potluckdb` next to it, and every program running on PotluckDB's library keeps that database the same on all devices that open it. Changes reach the other devices in about a second, and a device without the database gets it from the bucket.
