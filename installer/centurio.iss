; Inno Setup script for Centurio.
; Packages the `flet build windows` output into a Windows installer with a
; Start-Menu shortcut and an optional "launch at startup" checkbox.
;
; Build first:   flet build windows
; Then compile:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\centurio.iss
; Output:        installer\Output\CenturioSetup.exe

#define MyAppName "Centurio"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Centurio"
#define MyAppExeName "Centurio.exe"
; flet build windows output directory (relative to this script's parent):
#define BuildDir "..\build\windows"

[Setup]
AppId={{B2F1C7A0-6C1E-4D2E-9E4A-CENTURIO0001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=CenturioSetup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Запускать Centurio при входе в Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--hidden"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
