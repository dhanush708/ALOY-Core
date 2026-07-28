; ALOY — Inno Setup Installer Script
; Version: 1.0.0
; Author: Dhanush A.
; Website: https://github.com/dhanush708/aloy
;
; Prerequisites:
;   1. Inno Setup 6+ from https://jrsoftware.org/isinfo.php
;   2. Run build_windows.bat first to produce dist/ALOY/
;   3. Run: ISCC.exe installer/aloy.iss

#define AppName "ALOY"
#define AppVersion "1.0.1"
#define AppPublisher "Dhanush A."
#define AppURL "https://github.com/dhanush708/aloy"
#define AppExeName "ALOY.exe"
#define AppDescription "Local-First Personal AI Companion"

[Setup]
; Basic metadata
AppId={{A10Y-AI-COMPANION-V1-2026}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; Install location
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=no

; Output
OutputDir=..\dist\installer
OutputBaseFilename=ALOY-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\aloy.ico
Compression=lzma2/ultra64
SolidCompression=yes

; UI styling
WizardStyle=modern
WizardSizePercent=120
ShowLanguageDialog=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

; Windows requirements
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequiredOverridesAllowed=dialog

; Signing (fill in if you have a code signing certificate)
;SignTool=signtool
;SignedUninstaller=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Add to Start Menu"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main application (from PyInstaller dist)
Source: "..\dist\ALOY\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start menu shortcut
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\_internal\assets\icons\aloy.ico"; Comment: "{#AppDescription}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (if selected)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\_internal\assets\icons\aloy.ico"; Comment: "{#AppDescription}"; Tasks: desktopicon

[Run]
; Open ALOY after setup completes
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; Add Windows Firewall exception for ALOY server (port 8000 — localhost only)
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""ALOY Local Server"" dir=in action=allow protocol=TCP localport=8000 remoteip=127.0.0.1"; StatusMsg: "Configuring firewall..."; Flags: runhidden

[UninstallDelete]
; Clean up data folder on uninstall (optional — warn user first)
; Type: filesandordirs; Name: "{app}\data"

[Code]
// Check for minimum Windows 10 version
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then begin
    MsgBox('ALOY requires Windows 10 or later.', mbCriticalError, MB_OK);
    Result := False;
  end else
    Result := True;
end;

// After installation completes, prompt the user to download Ollama
procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    if MsgBox(
      'ALOY requires Ollama to run AI models locally.' + #13#10 + #13#10 +
      'Ollama is free, open-source, and takes about 2 minutes to install.' + #13#10 + #13#10 +
      'Download Ollama now? (Recommended)',
      mbConfirmation, MB_YESNO
    ) = IDYES then begin
      ShellExec('open', 'https://ollama.com/download/windows', '', '', SW_SHOW, ewNoWait, ErrorCode);
    end;
  end;
end;
