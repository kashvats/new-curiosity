# AI Project Auditor - VSCode Extension

This is a lightweight VSCode extension that wraps the AI Project Auditor into a native editor Webview. 
Because the AI engine runs locally via Docker (FastAPI + Vite), this extension acts as a seamless bridge, pulling the local dashboard straight into your coding environment!

## How to Install Locally

1. Open a terminal in this `vscode-extension` directory.
2. Install the VSCode Extension CLI:
   ```bash
   npm install -g @vscode/vsce
   ```
3. Package the extension into a `.vsix` file:
   ```bash
   vsce package
   ```
4. Install the extension in VSCode:
   - Go to the **Extensions** tab in VSCode (`Ctrl+Shift+X`).
   - Click the `...` menu in the top right of the extensions pane.
   - Select **Install from VSIX...**
   - Choose the `ai-project-auditor-1.0.0.vsix` file you just generated.

## Usage

1. Make sure your Docker containers (`backend` and `frontend`) are running locally.
2. Open the Command Palette (`Ctrl+Shift+P`).
3. Type and select: **AI Auditor: Open Dashboard**.
4. The Auditor UI will instantly pop up in a new editor tab!
