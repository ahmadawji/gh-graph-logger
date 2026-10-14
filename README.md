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

We recommend installing with [`pipx`](https://pypa.github.io/pipx/). `pipx` installs Python CLI tools in isolated environments while making them available globally in your terminal, so they never conflict with your other projects.

### 1. Prerequisites

Make sure you have:
- **Python 3.10+** (`python --version`)
- **Git** (`git --version`)
- **pipx** (if you don't have it yet, run `pip install pipx` followed by `pipx ensurepath`, then restart your terminal)

### 2. Install directly from GitHub

Run this single command in your terminal:

```bash
pipx install git+https://github.com/ahmadawji/gh-graph-logger.git
```

This automatically installs both `ghlog` and `gh-graph-logger` CLI commands globally. You can now use `ghlog` from anywhere!

---

## 🔄 Upgrading & Uninstalling

### Upgrading to the latest version
When new updates or bug fixes are pushed to GitHub, update your installation with a single command:

```bash
pipx upgrade gh-graph-logger
```

### Uninstalling
If you ever want to remove the tool:

```bash
pipx uninstall gh-graph-logger
```

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

## 📖 Subcommand Guide & Reference

### 1. `ghlog` (or `ghlog collect`) — Daily Commit Logging

The core daily command. Run it from inside any of your git repositories at the end of the day.

```bash
ghlog
```

**How it works:**
1. Collects all commits you authored today (since midnight, or since your last push).
2. Opens your default text editor (`$GIT_EDITOR`, `$EDITOR`, or Notepad/Vim) with a draft of the commit subjects.
3. You can review, edit, or delete any confidential lines you do not want to log. Lines starting with `#` are instructions and will be ignored.
4. When you save and close your editor, it asks for confirmation:
   ```text
   Push 3 commit(s) for 'my-project' to log repo? [y/N]: 
   ```
5. On `y`, it syncs your log repository (`git pull --rebase`), writes the entry into `<project>/YYYY-MM-DD.md`, commits, and pushes to GitHub.

#### Useful Flags:
* **Log commits from earlier dates (`--since`):**
  If you missed logging yesterday or want to capture a longer timeframe:
  ```bash
  ghlog --since "2026-10-01"
  ghlog --since "yesterday"
  ghlog --since "3 days ago"
  ```
* **Filter by author email (`--author`):**
  If you work in a repository with multiple authors or use different emails:
  ```bash
  ghlog --author "work@company.com"
  ```
* **Custom project name (`--project`):**
  By default, `ghlog` uses the folder name of your repository. You can give it a custom name:
  ```bash
  ghlog --project "payment-gateway"
  ```
* **Non-interactive / Skip confirmation (`--yes` or `-y`):**
  Skips the `[y/N]` confirmation prompt and pushes automatically (great for automation):
  ```bash
  ghlog --yes
  ```

---

### 2. `ghlog init` — Configure Your Log Repository

Sets up the connection between `ghlog` and your GitHub log repository.

#### Interactive Setup (Recommended for beginners):
Simply run:
```bash
ghlog init
```
It will guide you through:
- **Log repository URL:** Your GitHub repo (e.g. `git@github.com:username/daily-log.git`)
- **GitHub email:** Your verified GitHub email address (needed for contribution squares to count)
- **Root directory:** Where to save the clone (press Enter for the default `~/.gh-graph-logger`)

#### Non-Interactive Setup (Flags):
You can also pass all settings directly in one command:
```bash
ghlog init \
  --url git@github.com:username/daily-log.git \
  --email your-email@example.com \
  --yes
```

#### Other `init` Options:
* `--root <directory>`: Specify a custom root folder where the clone will live (e.g. `--root D:\logs`).
* `--path <existing-folder>`: Point `ghlog` to a repository you already cloned manually instead of cloning a new one.
* `--branch <branch>`: Specify a target branch (defaults to your remote default branch or `main`).

---

### 3. `ghlog check` — Health Check & Diagnostics

Verifies that everything is configured correctly and your environment is ready to log commits:

```bash
ghlog check
```

**What it tests:**
* ✅ **Git executable:** Checks that `git` is installed and on your system `PATH`.
* ✅ **Inside git repository:** Checks that your current directory is a valid git repository.
* ✅ **Log repository clone:** Checks that your local clone exists, is undamaged, and matches your configured URL.
* ✅ **Remote access:** Checks that your computer can reach GitHub over the network (`git ls-remote`).

If any check fails, `ghlog check` will print a helpful hint explaining how to fix it!

---

### 4. `ghlog config --show` — View Your Current Settings

Displays your current configuration saved in `~/.gh-graph-logger/config.json`:

```bash
ghlog config --show
```

**Example Output:**
```text
Configuration file: C:\Users\admin\.gh-graph-logger\config.json
  log_repo_url: git@github.com:username/daily-log.git
  clone_path:   C:\Users\admin\.gh-graph-logger\daily-log
  branch:       main
  github_email: your-email@example.com
  last_push:
    backend-api: 2026-10-14T14:30:00Z
```

---

### Quick Reference Summary

| Command | Purpose |
|---|---|
| `ghlog` | Daily logging: grabs today's commits, opens editor, confirms, and pushes |
| `ghlog --since "2 days ago"` | Log commits from a custom time window |
| `ghlog --project custom-name` | Override the project folder name in your log repo |
| `ghlog --yes` | Push automatically without the confirmation prompt |
| `ghlog init` | Interactive first-time setup for your log repo |
| `ghlog check` | Diagnostics check: verifies git, work repo, clone, and remote access |
| `ghlog config --show` | Display active configuration settings and last push timestamps |
| `ghlog --help` | Show the command-line help manual |
| `ghlog init --help` | Show all options available for the `init` command |

---

## 🧠 How It Works Under the Hood

Curious about how `ghlog` handles safe subprocess execution, atomic configuration saves, and security hardening against argument injection?

👉 **Read the full [Architecture & Deep Dive Guide](docs/how_it_works.md)** for:
- Detailed sequence diagrams of the daily workflow
- Breakdown of the 3-module architecture (`gitutil.py`, `config.py`, `cli.py`)
- Real-world production hardening (protocol injection defense, push failure recovery, Windows path handling)
- Testing architecture and CI design across 57 automated tests

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
