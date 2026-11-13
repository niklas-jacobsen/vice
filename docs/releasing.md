# Releasing

## One-time setup

1. **Make the repository public** (Settings → General → Danger Zone).
2. **Reserve the name on PyPI.** Create an account, then add a *pending trusted
   publisher* at <https://pypi.org/manage/account/publishing/>:
   - PyPI project name: `vice-ai`
   - Owner / repository: `niklas-jacobsen` / `vice`
   - Workflow: `release.yml`
   - Environment: `pypi`
3. **Create the `pypi` environment** in the GitHub repository (Settings → Environments).
   No secrets are needed; trusted publishing uses a short-lived token.
4. **Create the Homebrew tap**: a public repository named `homebrew-tap` under your
   account, with `packaging/homebrew/vice-ai.rb` copied to `Formula/vice-ai.rb`.

## Each release

1. Update `version` in `pyproject.toml` and `__version__` in `src/vice_ai/__init__.py`.
   They must match.
2. Add a section to `CHANGELOG.md`.
3. Merge to `main`, then tag and push:

   ```bash
   git tag v0.1.0
   ```

   ```bash
   git push origin v0.1.0
   ```

4. The **Release** workflow runs the tests, checks the tag matches the version, builds
   the sdist and wheel, publishes to PyPI, and creates a GitHub Release with both files
   attached and generated notes.
5. Update the tap. The build job's log prints the sdist checksum; or compute it:

   ```bash
   curl -sL https://files.pythonhosted.org/packages/source/v/vice-ai/vice_ai-0.1.0.tar.gz | shasum -a 256
   ```

   Put the new `url` and `sha256` in `Formula/vice-ai.rb` in the tap and push.
6. Check both install paths on a clean machine or user account:

   ```bash
   pipx install "vice-ai[mcp]"
   ```

   ```bash
   brew install niklas-jacobsen/tap/vice-ai
   ```

## Not yet verified

- The Release workflow has not run; it will first run on the first tag.
- The Homebrew formula has not been installed from a tap. It installs from PyPI wheels
  into a private virtualenv, which is acceptable for a personal tap but not for
  homebrew-core.
- `brew services start vice-ai` and `vice start` both run the service. Use one.

## If the Jev model changes

`model` is pinned in `config.py`. To move to a newer Jev: change the pin, run the
evaluation harness (`docs/evaluation.md`), commit the regenerated
`default_calibration.json` and reports, and release.
