; Inno Setup script for the Eclipse Desktop Agent installer.
;
; Build the app first:   scripts\build_exe.bat   (produces dist\eclipse-agent\)
; Then compile this:     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\eclipse-setup.iss
; Output:                dist\installer\eclipse-setup-<version>.exe
;
; Installs per-user (no admin), shows the MIT license, and creates shortcuts to
; the settings app. The detailed preferences (AI model, voice, credentials, MCP)
; are configured in that settings app after install.

#define AppName "Eclipse Desktop Agent"
#define AppShort "Eclipse"
#define AppVersion "0.1.0"
#define AppPublisher "Patricio"
#define AppUrl "https://github.com/p5Patricio/eclipse-desktop-agent"
#define AppExe "eclipse-agent.exe"

[Setup]
AppId={{8B6D2A1C-3F4E-4C7A-9E2B-7A1D5C9F0E12}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
DefaultDirName={localappdata}\Programs\Eclipse
DefaultGroupName={#AppShort}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=eclipse-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Iniciar Eclipse al arrancar Windows"; GroupDescription: "Opciones:"; Flags: unchecked

[Files]
Source: "..\dist\eclipse-agent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Eclipse — Configuración"; Filename: "{app}\{#AppExe}"; Parameters: "settings"
Name: "{group}\{cm:UninstallProgram,{#AppShort}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Eclipse"; Filename: "{app}\{#AppExe}"; Parameters: "settings"; Tasks: desktopicon
Name: "{userstartup}\Eclipse"; Filename: "{app}\{#AppExe}"; Parameters: "settings"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "settings"; Description: "Abrir la configuración de Eclipse"; Flags: postinstall nowait skipifsilent
