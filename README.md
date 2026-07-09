# gh-graph-logger 🟩

> Never lose your GitHub contribution squares just because you're working in a private Bitbucket, GitLab, or enterprise repository.

`gh-graph-logger` is a lightweight, zero-dependency Node.js CLI tool. It attaches a silent `pre-push` git hook to your local repository. Every time you push code to your private remote, it securely pushes an encrypted, text-only log of your commit to a public GitHub repository, keeping your contribution graph green.

## ✨ Features

- **Zero Dependencies:** Built entirely with native Node.js (`fetch`, `readline`).
- **Interactive Setup:** No bash bootstrap scripts required.
- **Non-Blocking:** Runs asynchronously in the background and never blocks your push.
- **Secure Configuration:** Stores credentials in git config (global for PAT, local for repo details).

## 🚀 Installation

```bash
npm install -g gh-graph-logger
```

## 🛠️ Setup & Usage

1. Create a new, public repository on GitHub (for example: `daily-commits`) and initialize it with a `README.md`.
2. Generate a [GitHub Personal Access Token (PAT)](https://github.com/settings/tokens) with `repo` permissions.
3. In your local private repository, run:

```bash
gh-graph-logger init
```

You will be prompted for:

```text
Let's configure your GitHub connection.

GitHub Personal Access Token (PAT): <paste-your-token>
GitHub Username: <your-username>
Target GitHub Repository: daily-commits

✅ Successfully installed pre-push hook and saved configuration!
```

After setup, normal `git push` commands trigger a background sync via `.git/hooks/pre-push`.

## ⚙️ How It Works

When `gh-graph-logger init` runs, it:

1. Stores:
   - GitHub token in global config: `~/.gitconfig`
   - GitHub username + target repository in local `.git/config`
2. Installs/updates a managed `.git/hooks/pre-push` block that executes:
   - `gh-graph-logger sync` in the background

On each push, `sync` reads your latest commit hash/message, encrypts the log entry, and appends it to the target repository `README.md` using the GitHub REST API.

## 📝 License

MIT — see the [LICENSE](/LICENSE) file.
