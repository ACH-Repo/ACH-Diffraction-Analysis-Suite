# Releasing to PyPI

Step-by-step, because this is the kind of thing nobody remembers between releases.

**One-time setup is steps 1–2.** Every release after that is steps 3–8.

---

## 1. Accounts and tokens (once)

You need an account on **both** indexes — they are completely separate systems
with separate logins:

- <https://test.pypi.org/account/register/> — the rehearsal index
- <https://pypi.org/account/register/> — the real one

Both require 2FA before you can upload. Enable it when prompted.

Then create an **API token** on each:

1. Account settings → *API tokens* → *Add API token*
2. Scope: "Entire account" for the first upload. After the project exists you can
   replace it with a token scoped to just this project, which is safer.
3. Copy the token immediately — it is shown **once**. It starts with `pypi-`.

## 2. Store the tokens (once)

Create `C:\Users\<you>\.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc...your-real-token...

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgENdGVzdC5weXBp...your-test-token...
```

`username` is the literal string `__token__` for both — not your account name.
The token itself goes in `password`.

This file contains upload credentials. Keep it out of the repository (it lives in
your home directory, not here) and do not paste its contents into a chat, an
issue, or a commit.

> Prefer not to keep tokens on disk? Skip `.pypirc` and let twine prompt you:
> it asks for username and password on each upload. Use `__token__` and paste
> the token at the prompt.

## 3. Decide the version

Edit `version` in `pyproject.toml`.

**PyPI will not let you reuse or overwrite a version, ever** — not even if you
delete the release. A botched `0.2.0` means the next attempt has to be `0.2.1`.
This is the single biggest reason to rehearse on TestPyPI first.

While below `1.0`, bump the minor for feature or command changes (`0.2.0` →
`0.3.0`) and the patch for fixes (`0.2.0` → `0.2.1`).

## 4. Build

```bash
cd C:\Users\<you>\Documents\Github\ACH-Diffraction-Analysis-Suite
rm -rf dist build src/*.egg-info      # stale artefacts get uploaded otherwise
python -m build
```

Produces two files in `dist/`:

```
ach_diffraction_suite-0.2.0-py3-none-any.whl    # what pip normally installs
ach_diffraction_suite-0.2.0.tar.gz              # source archive, the fallback
```

**Always delete `dist/` first.** `twine upload dist/*` uploads everything it
finds, including leftovers from previous versions.

## 5. Check before uploading

```bash
python -m twine check dist/*
```

Both files must say `PASSED`. This validates the metadata and, importantly, that
the README renders on PyPI — a malformed README is rejected *after* upload,
which burns the version number.

Also confirm the data file made it in, since a missing `resource.htm` breaks `pt`
and is invisible until someone runs it:

```bash
python -c "import zipfile,glob; print([n for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist() if n.endswith('.htm')])"
```

Expected: `['achdiff/data/resource.htm']`

## 6. Rehearse on TestPyPI

```bash
python -m twine upload --repository testpypi dist/*
```

Then install it somewhere clean and actually run a command. TestPyPI does not
mirror real PyPI, so dependencies must come from the real index:

```bash
python -m venv C:\Temp\rehearse
C:\Temp\rehearse\Scripts\activate
pip install --index-url https://test.pypi.org/simple/ ^
            --extra-index-url https://pypi.org/simple/ ^
            ach-diffraction-suite
pp --help
pt --help
achdiff alias list
deactivate
```

That `--extra-index-url` is the part people forget; without it the install fails
trying to find numpy and pymatgen on TestPyPI.

## 7. Upload for real

Only once step 6 worked:

```bash
python -m twine upload dist/*
```

The project appears at
<https://pypi.org/project/ach-diffraction-suite/> within a minute or so.

## 8. Verify, then tell the lab

```bash
pip install ach-diffraction-suite
```

On each TOPAS PC, upgrading is now:

```bash
pip install --upgrade ach-diffraction-suite
```

Worth mentioning to colleagues on the first release:

- the old `.cmd` shims should be deleted so they cannot shadow the installed
  commands;
- `pf` now runs **prefit**, not tables — tables is `pt`;
- their config in `%APPDATA%\ach-diffraction\config.toml` is untouched by
  upgrades.

Tag the release so the published version is reproducible:

```bash
git tag -a v0.2.0 -m "Release 0.2.0"
git push origin v0.2.0
```

---

## Quick reference

```bash
rm -rf dist build src/*.egg-info
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*     # rehearse
python -m twine upload dist/*                           # real
```

## When it goes wrong

| Symptom | Cause |
|---|---|
| `403 Forbidden` | Wrong token, or `username` is not the literal `__token__`. Test and real PyPI tokens are not interchangeable. |
| `400 File already exists` | That version is already published. Bump the version; it cannot be overwritten. |
| `InvalidDistribution` on check | Malformed metadata or README. Fix before uploading, not after. |
| Install fails on numpy/pymatgen from TestPyPI | Missing `--extra-index-url https://pypi.org/simple/`. |
| `pt` fails with a missing resource | `resource.htm` was left out of the build. Check step 5. |
| Uploaded the wrong files | `dist/` still held an older build. Always clear it first. |
