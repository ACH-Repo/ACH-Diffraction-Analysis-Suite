# Releasing to PyPI

Step-by-step, because this is the kind of thing nobody remembers between releases.

**One-time setup is steps 1–2.** Every release after that is steps 3–7.

---

## 1. Account and token (once)

Register at <https://pypi.org/account/register/> and enable 2FA — uploads are
blocked until you do.

Then create an **API token**: Account settings → *API tokens* → *Add API token*.

- Scope "Entire account" for the first upload. Once the project exists, replace
  it with a token scoped to just this project.
- Copy it immediately — it is shown **once**. It starts with `pypi-`.

## 2. Store the token (once)

Create `C:\Users\<you>\.pypirc`:

```ini
[distutils]
index-servers = pypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc...your-token...
```

`username` is the literal string `__token__` — not your account name. The token
goes in `password`.

This file is upload credentials. It lives in your home directory, not in the
repository; don't paste its contents into a chat, an issue, or a commit.

> Prefer not to keep it on disk? Skip `.pypirc` and let twine prompt you on each
> upload. Use `__token__` as the username and paste the token at the prompt.

## 3. Decide the version

Edit `version` in `pyproject.toml`. `achdiff.__version__` follows automatically —
it reads the installed metadata rather than repeating the number.

**PyPI never lets you reuse a version**, even if you delete the release. A
botched `0.2.0` means the next attempt has to be `0.2.1`. This is the one
genuinely irreversible step, which is why step 5 exists.

Below `1.0`: bump the minor for features or command changes, the patch for fixes.

## 4. Build

```bash
cd C:\Users\<you>\Documents\Github\ACH-Diffraction-Analysis-Suite
rm -rf dist build src/*.egg-info      # stale artefacts get uploaded otherwise
python -m build
```

Produces two files in `dist/`:

```
ach_diffraction_suite-<version>-py3-none-any.whl    # what pip normally installs
ach_diffraction_suite-<version>.tar.gz              # source archive, the fallback
```

**Always clear `dist/` first.** `twine upload dist/*` uploads everything it finds,
including leftovers from earlier versions.

## 5. Verify before uploading

Since the version can't be reclaimed, do these three checks every time.

**a. Metadata and README render:**

```bash
python -m twine check dist/*
```

Both files must say `PASSED`. A malformed README is rejected *after* upload,
which burns the version number.

**b. The data file is in the wheel.** A missing `resource.htm` breaks `pt` and is
invisible until someone runs it:

```bash
python -c "import zipfile,glob; print([n for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist() if n.endswith('.htm')])"
```

Expected: `['achdiff/data/resource.htm']`

**c. Install the built wheel and actually run it.** This is the important one: it
catches anything that works in the development tree but is missing from the
package.

```bash
pip uninstall -y ach-diffraction-suite
pip install dist/ach_diffraction_suite-<version>-py3-none-any.whl
cd %TEMP%
python -c "import achdiff; print(achdiff.__version__, achdiff.__file__)"
```

The path must be in `site-packages`, **not** your `Github` folder — if it points
at the source tree, an editable install is shadowing the real one and you are not
testing what you are about to publish. Then drive the tools against real data:

```bash
pp -s -c -x png          # in a folder of TOPAS output
pt                       # exercises resource.htm from the install
achdiff alias list
```

Reinstall in editable mode (`pip install -e .`) when you go back to development.

## 6. Upload

```bash
python -m twine upload dist/*
```

The project appears at <https://pypi.org/project/ach-diffraction-suite/> within
a minute or so.

## 7. Verify and tell the lab

```bash
pip install ach-diffraction-suite
```

On each TOPAS PC, updating is now:

```bash
pip install --upgrade ach-diffraction-suite
```

Worth mentioning to colleagues on the first release:

- delete the old `.cmd` shims so they cannot shadow the installed commands;
- `pf` runs **prefit**, not tables — tables is `pt`;
- their config in `%APPDATA%\ach-diffraction\config.toml` survives upgrades;
- trusted parameters are per person: register your own with
  `achdiff trusted add <phase> --from <fit>.out -u <your-id>`.

Tag the release so the published version stays reproducible:

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
pip uninstall -y ach-diffraction-suite && pip install dist/*.whl   # then run it
python -m twine upload dist/*
```

## When it goes wrong

| Symptom | Cause |
|---|---|
| `403 Forbidden` | Wrong token, or `username` is not the literal `__token__`. |
| `400 File already exists` | That version is published. Bump it; it cannot be overwritten. |
| `InvalidDistribution` on check | Malformed metadata or README. Fix before uploading, not after. |
| `achdiff.__file__` shows your Github folder | An editable install is shadowing the wheel. `pip uninstall` first. |
| `pt` fails with a missing resource | `resource.htm` was left out of the build. Check 5b. |
| Uploaded the wrong files | `dist/` still held an older build. Always clear it first. |

> Rehearsing on <https://test.pypi.org> first is possible — separate account and
> token, upload with `--repository testpypi`, and install with
> `--extra-index-url https://pypi.org/simple/` so the real dependencies resolve.
> Step 5c covers most of what it would have caught.
