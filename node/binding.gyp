# Builds potluckdb.node, the Node-API addon, linked statically with PotluckDB's
# SQLite library, and test_extension.node, a loadable extension for the tests.
# Run it through scripts/build.js, which unpacks a core archive and passes its
# folder as potluckdb_core. Nothing is compiled when users install the package.
{
  'variables': {
    'potluckdb_core%': '',
  },
  'target_defaults': {
    'default_configuration': 'Release',
    'msvs_settings': {
      'VCCLCompilerTool': {
        'ExceptionHandling': 1,
      },
    },
    'xcode_settings': {
      'MACOSX_DEPLOYMENT_TARGET': '11.0',
    },
    'configurations': {
      'Debug': {
        'defines!': ['NDEBUG'],
        'defines': ['DEBUG', '_DEBUG'],
      },
      'Release': {
        'defines!': ['DEBUG', '_DEBUG'],
        'defines': ['NDEBUG'],
        'cflags': ['-O3'],
        'xcode_settings': {
          'GCC_OPTIMIZATION_LEVEL': '3',
          'DEAD_CODE_STRIPPING': 'YES',
        },
      },
    },
  },
  'targets': [
    {
      'target_name': 'potluckdb',
      'sources': ['src/better_sqlite3.cpp'],
      'include_dirs': [
        "<!(node -p \"require('node-addon-api').include_dir\")",
        '<(potluckdb_core)/include',
      ],
      # Node-API 8 is in every Node.js version from 12.22 on (and in Bun and
      # Deno), so one binary per platform serves Node.js 20 and later.
      'defines': ['NAPI_VERSION=8', 'NAPI_DISABLE_CPP_EXCEPTIONS', 'NODE_API_SWALLOW_UNTHROWABLE_EXCEPTIONS'],
      'cflags_cc': ['-std=c++20', '-fvisibility=hidden', '-fvisibility-inlines-hidden'],
      'xcode_settings': {
        'CLANG_CXX_LANGUAGE_STANDARD': 'c++20',
        'CLANG_CXX_LIBRARY': 'libc++',
        'GCC_SYMBOLS_PRIVATE_EXTERN': 'YES',
        'GCC_INLINES_ARE_PRIVATE_EXTERN': 'YES',
      },
      'msvs_settings': {
        'VCCLCompilerTool': {
          'AdditionalOptions': ['/std:c++20'],
        },
      },
      # The library's symbols are hidden, so the addon exports none of them
      # and never clashes with another SQLite in the same process.
      'conditions': [
        ['OS=="win"', {
          'libraries': ['<(potluckdb_core)/lib/static/sqlite3.lib'],
        }],
        ['OS=="mac"', {
          'libraries': ['<(potluckdb_core)/lib/static/libsqlite3.a'],
        }],
        ['OS=="linux"', {
          'libraries': ['<(potluckdb_core)/lib/static/libsqlite3.a', '-lpthread', '-ldl', '-lm'],
          'ldflags': ['-Wl,-Bsymbolic', '-Wl,--exclude-libs,ALL', '-Wl,--version-script=<(module_root_dir)/src/exports.map'],
        }],
      ],
    },
    {
      'target_name': 'test_extension',
      'sources': ['deps/test_extension.c'],
      'include_dirs': ['<(potluckdb_core)/include'],
    },
  ],
}
