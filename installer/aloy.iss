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
#define AppVersion "1.0.0"
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
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\icons\aloy.ico"; Comment: "{#AppDescription}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

; Desktop shortcut (if selected)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\icons\aloy.ico"; Comment: "{#AppDescription}"; Tasks: desktopicon

[Run]
; Launch ALOY after setup completes
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

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
