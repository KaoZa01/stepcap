# StepCap

[ภาษาไทย](README.md) · **English**

StepCap turns your clicks and typing into a step-by-step guide with screenshots, then exports it as Word, PDF, HTML or Markdown.
It is made for SOPs and how-to guides for your coworkers. Everything runs on your computer and nothing is sent anywhere.

![Guide view: steps with screenshots and a ring where you clicked](docs/images/guide.png)

## What it does

- **Record** every click, typed text and shortcut as a step, with a screenshot that rings the spot you clicked
- **Edit** the text of each step, reorder steps, add your own notes or pictures
- **Edit pictures**: draw arrows, boxes and text, blur, black out and crop
- **Hide private data automatically**: blurs emails, phone numbers, Thai ID numbers, card numbers and bank account numbers in screenshots
- **Guide me**: open a guide and StepCap points at the right button on your real screen, one step at a time, and moves on when you click it
- **Page**: combine several guides into one document
- **Export** to Word (.docx), PDF, HTML (one file that opens anywhere) or Markdown (.zip)

## Requirements

- Windows 11 (tested on Windows 11) with the Microsoft Edge WebView2 Runtime, which Windows 11 already has
- To run from source you also need Python 3.14

## Setup guide

### Everyone: use the installer

No Python and no admin rights needed.

1. Download `StepCap-Setup-<version>.exe` from the [Releases](https://github.com/KaoZa01/stepcap/releases/latest) page
2. Double-click the downloaded file
3. If a blue "Windows protected your PC" screen appears, click **More info**, then **Run anyway**
   (it appears because the file is not signed with a Microsoft certificate yet; it is not a virus)
4. Choose **English** or **ไทย** and click **OK**. StepCap starts in this language
5. Click **Next**, choose whether you want a desktop icon, then click **Install**
   - If StepCap is running, the installer asks you to close it first
   - If WebView2 is missing, the installer tells you to install it first
6. Click **Finish** and StepCap opens. Next time, open it from the Start menu or the desktop icon

StepCap is installed for your user only, in `%LOCALAPPDATA%\Programs\StepCap`.
To update, install the new version over the old one. To uninstall, go to **Settings > Apps > StepCap > Uninstall** (your guides in `Documents\StepCap` are kept).

Sending the installer to coworkers? [docs/install-guide.md](docs/install-guide.md) has install instructions in Thai and English, ready to paste next to the file.

### Developers: run from source

Open PowerShell and follow the steps.

**1. Install Python 3.14 and Git**

```powershell
winget install Python.Python.3.14
winget install Git.Git
```

When they are installed, close PowerShell and open it again so the `python` and `git` commands work. Then `python --version` should print `Python 3.14` (you can use the installer from python.org instead, but tick "Add python.exe to PATH")

<img src="docs/images/setup-1.svg" width="600" alt="PowerShell: winget installs Python and Git, then python --version prints Python 3.14.0">

**2. Get the code**

```powershell
git clone https://github.com/KaoZa01/stepcap.git
cd stepcap
```

<img src="docs/images/setup-2.svg" width="600" alt="PowerShell: git clone, then cd stepcap">

**3. Create a venv and install the libraries**

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

It is done when you see `Successfully installed ...`

<img src="docs/images/setup-3.svg" width="600" alt="PowerShell: python -m venv, then pip install prints Successfully installed">

**4. Start StepCap**

```powershell
.venv\Scripts\pythonw.exe app.py
```

The StepCap window opens (the terminal prints nothing more). If a StepCap installed from the .exe is running, quit it first: both use the same guides folder and cannot run at the same time.

<img src="docs/images/setup-4.svg" width="600" alt="PowerShell: pythonw.exe app.py">

<img src="docs/images/home.png" width="360" alt="The StepCap window that opens">

Next time, start it with the step 4 command from the `stepcap` folder.

### After setup

Clicking X hides StepCap to the orange icon in the tray at the bottom right. To really close it, right-click that icon and choose **Quit**.

## Quick start

![Home: the guide library and the New recording button](docs/images/home.png)

1. Click **+ New recording**, pick a screen, then click **Start recording**
2. Work in the program you want to teach as usual
3. Click **Stop recording** on the panel at the bottom right. The guide opens for editing straight away
4. Click **Export** and choose a file type

**Guide me:** open a guide and click **Guide me**. A panel appears at the right edge of the screen with the current step and its picture, and an orange box surrounds the button to click.
If the button can't be found but the window can, it points at the approximate spot. Typing steps move on when you type what was recorded; key and shortcut steps move on when you press them.
Passwords, hidden text and guides recorded before Guide me existed move on when you press Enter or Tab (you can always click **Next** yourself).
Guides recorded before Guide me existed point at the old position on the screen you selected. You can't start recording while Guide me is running.

<img src="docs/images/guide-me.png" width="320" alt="Guide me panel: the current step with its picture, a zoom button and Back/Next buttons">

The first time you open StepCap, your library has the guide "Sample: Getting started with StepCap" and short tips point at the main buttons. See the tips again in **Settings > Show the tips again**.

Switch the language in **Settings > ภาษา / Language**. New steps and the headings in exported files use the chosen language; guides you already made are not translated.

| Shortcut | What it does |
|---|---|
| Ctrl+Alt+R | Start / stop recording |
| Ctrl+Alt+P | Pause / resume |

## Where files are kept

Guides are kept in `Documents\StepCap`. Open this folder from **Settings > Open folder**.

> **Careful:** this folder also holds the original pictures before blurring. When you share a guide, send only the file you made with Export, never the whole folder.
> Automatic hiding only reads English letters and numbers, so check the pictures yourself before you share them.

Design guidelines are in [DESIGN.md](DESIGN.md) (Thai).

## License

MIT, see [LICENSE](LICENSE)
