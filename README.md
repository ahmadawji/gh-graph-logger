# gh-graph-logger 🟩
A zero-dependency CLI that silently syncs your private repository commits to your GitHub contribution graph.

 > Never lose your GitHub contribution squares just because you're working in a private Bitbucket, GitLab, or enterprise repository.



`gh-graph-logger` is a lightweight, zero-dependency Node.js CLI tool. It attaches a silent `pre-push` git hook to your local repository. Every time you push code to your private remote, it securely pushes an encrypted, text-only log of your commit to a public GitHub repository, keeping your contribution graph green.

## ✨ Features
* **Zero Dependencies:** Built entirely with native Node.js (`fetch`, `readline`). Fast and secure.
* **Interactive Setup:** No messy bash scripts required.
* **Non-Blocking:** Runs asynchronously in the background. It will never slow down your actual `git push`.
* **Secure Configuration:** Stores credentials natively in your local `git config`, not in easily-leaked `.env` files.

## 🚀 Installation

Install the package globally via npm:

```npm install -g gh-graph-logger```

## 🛠️ Setup & Usage

1.  Create a new, public repository on GitHub (e.g., `daily-commits`) and initialize it with a `README.md`.
    
2.  Generate a [GitHub Personal Access Token (PAT)](https://github.com/settings/tokens) with `repo` permissions.
    
3.  Navigate to your local private repository (e.g., your Bitbucket project) and run:
    

Bash

```
gh-graph-logger init
```
The CLI will walk you through an interactive prompt:

Plaintext

```
Let's configure your GitHub connection.

GitHub Personal Access Token (PAT): <paste-your-token>
GitHub Username: <your-username>
Target GitHub Repository: daily-commits

✅ Successfully installed pre-push hook and saved configuration!

```

**You're done.** Proceed with your normal workflow. Every `git push` will now trigger a background sync to your GitHub repo.

## ⚙️ How It Works

When you run `gh-graph-logger init`, the tool does two things:

1.  Saves your GitHub token to your global `~/.gitconfig` and your repo details to your local `.git/config`.
    
2.  Creates a `.git/hooks/pre-push` file in your repository that calls `gh-graph-logger sync`.
    

Whenever you push to your private remote, the hook reads your latest commit message and hash, and uses the GitHub REST API to append a line to your target GitHub repository's `README.md`.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.
