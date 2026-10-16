; StepCap installer: per user, no admin, Thai or English.
; Built by build.py: ISCC /DMyVersion=<app.VERSION> installer\StepCap.iss
; Takes dist\StepCap\ (PyInstaller) and makes dist\StepCap-Setup-<version>.exe.

#ifndef MyVersion
  #define MyVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B2C1E-8A47-4D3B-9C2E-5B1A7D4E9F21}
AppName=StepCap
AppVersion={#MyVersion}
AppVerName=StepCap {#MyVersion}
AppPublisher=StepCap
DefaultDirName={localappdata}\Programs\StepCap
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; StepCap holds this mutex while it runs: Setup asks to close it first
AppMutex=StepCapRunning
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
ShowLanguageDialog=yes
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=StepCap-Setup-{#MyVersion}
SetupIconFile=..\build\StepCap.ico
UninstallDisplayIcon={app}\StepCap.exe
UninstallDisplayName=StepCap
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "th"; MessagesFile: "compiler:Languages\Thai.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
th.NeedWebView2=ต้องติดตั้ง Microsoft Edge WebView2 Runtime ก่อน%n%nขอให้ฝ่ายไอทีติดตั้งให้ หรือดาวน์โหลดจากเว็บไซต์ของ Microsoft แล้วเปิดตัวติดตั้งนี้อีกครั้ง
en.NeedWebView2=Microsoft Edge WebView2 Runtime is needed first.%n%nAsk your IT team to install it, or download it from Microsoft's website, then run this installer again.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\StepCap\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\StepCap"; Filename: "{app}\StepCap.exe"
Name: "{autodesktop}\StepCap"; Filename: "{app}\StepCap.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\StepCap.exe"; Description: "{cm:LaunchProgram,StepCap}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; written by [Code] below, so the uninstaller doesn't know it otherwise
Type: files; Name: "{app}\lang.txt"

[Code]
const
  WebView2Key = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasVersion(Root: Integer; Key: String): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;

// WebView2 shows StepCap's window; without it the app can't open, so say so and stop
function InitializeSetup(): Boolean;
begin
  Result := HasVersion(HKLM, 'SOFTWARE\WOW6432Node\' + WebView2Key) or
            HasVersion(HKCU, 'Software\' + WebView2Key);
  if not Result then
    SuppressibleMsgBox(CustomMessage('NeedWebView2'), mbCriticalError, MB_OK, IDOK);
end;

// the language picked here is StepCap's first language (app.py reads lang.txt)
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\lang.txt'), ActiveLanguage(), False);
end;
