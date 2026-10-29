; Inno Setup script - builds dist\ScreenRecStudio-<version>-Setup.exe
; Usage: ISCC /DAppVersion=1.0.0 /DRepoUrl=https://github.com/ChampionXperience/screenrec-studio packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef RepoUrl
  #define RepoUrl "https://github.com/ChampionXperience/screenrec-studio"
#endif
#define AppName "ScreenRec Studio"
#define AppExe "ScreenRecStudio.exe"

[Setup]
; AppId never changes: it lets new versions update the existing installation
AppId={{6E4C2B1F-8A3D-4F7B-9C55-1D2E3F4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=ChampionXperience
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
; Per-user install (no admin / UAC): %LOCALAPPDATA%\Programs\ScreenRec Studio. Lets updates install silently.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=ScreenRecStudio-{#AppVersion}-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
CloseApplications=force
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany=ChampionXperience

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ScreenRecStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files of the previous version so updates never mix old and new libraries
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Interactive install: optional "Launch" checkbox. Silent update (from inside the app): relaunch automatically.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent
