; =====================================================================
; ALOY — Inno Setup Production Windows Installer Script
; Produces: dist/installer/ALOY-Setup-1.0.0.exe
; AppID: {{A90F8C72-8812-4B3B-9A4E-7C12F8B701D2}
; =====================================================================

#define MyAppName "ALOY"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Dhanush Anbu"
#define MyAppURL "https://github.com/dhanush708/ALOY-Core"
#define MyAppExeName "ALOY.exe"
#define MyAppId "{{A90F8C72-8812-4B3B-9A4E-7C12F8B701D2}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=ALOY-Setup-1.0.0
SetupIconFile=..\assets\icons\aloy.ico
WizardImageFile=..\assets\icons\aloy_wizard_large.bmp
WizardSmallImageFile=..\assets\icons\aloy_wizard_small.bmp
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequiredOverridesAllowed=commandline dialog
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main Executable Binary
Source: "..\dist\ALOY\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Bundled Runtime Dependencies
Source: "..\dist\ALOY\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; License & Documentation
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\icons\aloy.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\icons\aloy.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Custom Pascal Script to handle optional user data cleanup on Uninstall
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataDir := ExpandConstant('{userlocalappdata}\ALOY');
    if DirExists(AppDataDir) then
    begin
      if MsgBox('Do you also want to delete all personal user data (conversations, memories, database, logs, and settings) stored in %LOCALAPPDATA%\ALOY\?' + #13#10 + #13#10 + 'Click No to preserve your data for future reinstalls.', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataDir, True, True, True);
      end;
    end;
  end;
end;
