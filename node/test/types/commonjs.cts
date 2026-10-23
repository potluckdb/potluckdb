// potluckdb's types from CommonJS (resolved through package.json "exports").
import Database = require('potluckdb');

const db: Database.Database = new Database('app.db', { readonly: false, timeout: 1000 });
const version: string = Database.coreVersion;
const row = db.prepare<[], { p: string; s: string }>('select potluckdb_version() as p, sqlite_version() as s').get();
const p: string | undefined = row?.p;
const info: Database.RunResult = db.prepare('insert into t values (?)').run(1);
const plan: unknown[] = db.explain('select 1');
const insertMany = db.transaction((values: number[]) => values.length);
const count: number = insertMany([1, 2]);
db.function('twice', (x: number) => 2 * x).aggregate('total', { start: 0, step: (t: number, x: number) => t + x });
db.loadExtension('ext', 'entry_point');
const error: InstanceType<typeof Database.SqliteError> = new Database.SqliteError('message', 'SQLITE_ERROR');
const code: string = error.code;
db.close();
export { version, p, info, plan, count, code };
