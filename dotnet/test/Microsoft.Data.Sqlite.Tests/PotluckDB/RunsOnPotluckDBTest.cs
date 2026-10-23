// Not from efcore: makes sure that the suite runs on PotluckDB's SQLite, not on
// another one that happens to be in the test's dependencies.
using SQLitePCL;
using Xunit;

namespace Microsoft.Data.Sqlite.PotluckDB;

public class RunsOnPotluckDBTest
{
    [Fact]
    public void Suite_runs_on_PotluckDB()
    {
        Assert.Equal("potluckdb", raw.GetNativeLibraryName());
        using var connection = new SqliteConnection("Data Source=:memory:");
        connection.Open();
        var command = connection.CreateCommand();
        command.CommandText = "SELECT potluckdb_version()";
        Assert.NotEmpty((string)command.ExecuteScalar()!);
    }
}
