---
title: Verify downloads
description: Check that a PotluckDB archive is the one our release built.
---

Every release lists the SHA-256 checksum of each file in `SHA256SUMS`, and
signs each file with [Sigstore](https://www.sigstore.dev/), from the release
workflow itself. No signing keys are kept anywhere.

## Checksum

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

## Signature

With [cosign](https://docs.sigstore.dev/cosign/system_config/installation/):

```sh
cosign verify-blob --bundle <file>.sigstore.json \
  --certificate-identity-regexp '^https://github.com/potluckdb/core/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com <file>
```

`Verified OK` means the file was built and signed by PotluckDB's release
workflow and has not changed since.
