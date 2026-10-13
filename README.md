# gh-graph-logger 🟩

A zero-dependency Python CLI tool to easily log your daily commits to a GitHub repository and keep your contribution graph active.

> Keep your GitHub contribution graph active even when working on private client repositories, enterprise Git instances, or offline repositories.

---

## ✨ Features

- **Zero Runtime Dependencies**: Built entirely with Python standard library modules (`subprocess`, `json`, `argparse`, `pathlib`).
- **Single Daily Command**: Run `ghlog` at the end of the day to fetch your commits, review them in your editor, and log them in one smooth step.
- **Privacy & Security First**: Edit or redact any commit subjects in your editor before they are logged. Never logs sensitive code or internal diffs.
- **Cross-Platform**: Fully tested and supported on Windows, macOS, and Linux across Python 3.10–3.14.

---

## 🚀 Installation

Install using `pip` (or `pipx`):

```bash
pip install .
```

This installs both `ghlog` and `gh-graph-logger` CLI commands.

---

## 🛠️ Getting Started

### 1. Initialize Log Repository

Create a repository on GitHub (e.g. `daily-log`) and run:

```bash
ghlog init --url git@github.com:yourusername/daily-log.git --email your-github@email.com
```

Or simply run `ghlog init` and follow the interactive prompts.

### 2. Daily Workflow

Whenever you finish working in any repository, simply run:

```bash
ghlog
```

`ghlog` will automatically:
1. Fetch all commits authored by you since midnight (or since your last push).
2. Open your preferred editor (`$GIT_EDITOR`, `$EDITOR`, `core.editor`, or Notepad/Vim) so you can review and delete any commits you don't wish to log.
3. Prompt for confirmation (`Push N commit(s) for '<project>' to log repo? [y/N]`).
4. Commit and push the summary entry into `<clone>/<project>/YYYY-MM-DD.md`.

---

## 📖 Command Reference

| Command | Description |
|---|---|
| `ghlog` | Daily logging: grabs today's commits, opens editor, confirms, and pushes. |
| `ghlog --since "2026-10-01"` | Log commits since a specific date or time. |
| `ghlog --yes` | Skip confirmation prompt and push automatically. |
| `ghlog --project custom-name` | Override project name (defaults to repository directory name). |
| `ghlog init` | Initialize or configure the log repo clone. |
| `ghlog check` | Verify git environment, repository status, and log repo access. |
| `ghlog config --show` | Display current configuration settings. |

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
