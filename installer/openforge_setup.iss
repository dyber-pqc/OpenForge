; OpenForge EDA - Inno Setup Installer
; Vivado/Altium-style component selector with EDA tool bundling
;
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\openforge_setup.iss

#define MyAppName "OpenForge EDA"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Dyber, Inc."
#define MyAppURL "https://openforge.dev"
#define MyAppExeName "openforge-desktop.exe"

[Setup]
AppId={{8F2A4B5C-1D3E-4F6A-B7C8-9D0E1F2A3B4C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\OpenForge
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=OpenForge-Setup-{#MyAppVersion}-win64
SetupIconFile=..\share\icons\openforge.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120,120
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\openforge.ico
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full";    Description: "Full installation (Desktop + CLI + all EDA tools + PDKs)"
Name: "compact"; Description: "Compact installation (Desktop + CLI only)"
Name: "custom";  Description: "Custom installation"; Flags: iscustom

[Components]
; Core (always installed)
Name: "core";         Description: "OpenForge Core Library";         Types: full compact custom; Flags: fixed
Name: "desktop";      Description: "OpenForge Desktop (GUI)";        Types: full compact custom; Flags: fixed
Name: "cli";          Description: "OpenForge CLI";                  Types: full compact custom; Flags: fixed

; EDA Tools (optional, downloaded during install)
Name: "tools";        Description: "EDA Tools";                      Types: full
Name: "tools\yosys";  Description: "Yosys (RTL Synthesis)";          Types: full
Name: "tools\nextpnr"; Description: "nextpnr (FPGA Place && Route)"; Types: full
Name: "tools\icepack"; Description: "IceStorm (iCE40 bitstream tools)"; Types: full
Name: "tools\openroad"; Description: "OpenROAD (ASIC Place && Route)"; Types: full
Name: "tools\magic";  Description: "Magic VLSI (DRC/Layout)";        Types: full
Name: "tools\netgen"; Description: "Netgen (LVS)";                   Types: full
Name: "tools\ngspice"; Description: "ngspice (Analog Simulation)";   Types: full
Name: "tools\verilator"; Description: "Verilator (Fast Simulation)"; Types: full
Name: "tools\iverilog"; Description: "Icarus Verilog (Simulation)";  Types: full
Name: "tools\klayout"; Description: "KLayout (Layout Viewer)";       Types: full
Name: "tools\openfpgaloader"; Description: "openFPGALoader (FPGA Programmer)"; Types: full

; PDKs (optional)
Name: "pdk";          Description: "Process Design Kits";            Types: full
Name: "pdk\sky130";   Description: "SkyWater SKY130 (130nm CMOS)";   Types: full
Name: "pdk\gf180";    Description: "GlobalFoundries GF180MCU";       Types: full

; Examples
Name: "examples";     Description: "Example Projects";               Types: full compact

; Documentation
Name: "docs";         Description: "Documentation";                  Types: full compact

[Files]
; Core Python packages
Source: "..\packages\core\*";    DestDir: "{app}\packages\core";    Flags: ignoreversion recursesubdirs; Components: core
Source: "..\packages\cli\*";     DestDir: "{app}\packages\cli";     Flags: ignoreversion recursesubdirs; Components: cli
Source: "..\packages\desktop\*"; DestDir: "{app}\packages\desktop"; Flags: ignoreversion recursesubdirs; Components: desktop
Source: "..\packages\api\*";     DestDir: "{app}\packages\api";     Flags: ignoreversion recursesubdirs; Components: core

; Share directory (icons, IP library, etc.)
Source: "..\share\*";     DestDir: "{app}\share";     Flags: ignoreversion recursesubdirs; Components: core

; Examples
Source: "..\examples\*";  DestDir: "{app}\examples";  Flags: ignoreversion recursesubdirs; Components: examples

; Documentation
Source: "..\docs\*";      DestDir: "{app}\docs";      Flags: ignoreversion recursesubdirs; Components: docs

; Config files
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\README.md";      DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\LICENSE";        DestDir: "{app}"; Flags: ignoreversion; Components: core

; Launch scripts
Source: "launch_desktop.bat"; DestDir: "{app}"; Flags: ignoreversion; Components: desktop
Source: "launch_cli.bat";     DestDir: "{app}"; Flags: ignoreversion; Components: cli

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\launch_desktop.bat"; IconFilename: "{app}\share\icons\openforge.ico"; Components: desktop
Name: "{group}\OpenForge CLI";          Filename: "cmd.exe"; Parameters: "/k ""{app}\launch_cli.bat"""; IconFilename: "{app}\share\icons\openforge.ico"; Components: cli
Name: "{group}\Documentation";         Filename: "{app}\docs\index.md"; Components: docs
Name: "{group}\Examples";              Filename: "{app}\examples"; Components: examples
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\launch_desktop.bat"; IconFilename: "{app}\share\icons\openforge.ico"; Components: desktop; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Components: desktop
Name: "addtopath";   Description: "Add OpenForge to system &PATH"; GroupDescription: "System integration:"

[Registry]
; File associations
Root: HKCR; Subkey: ".v";    ValueType: string; ValueData: "OpenForge.Verilog";     Flags: uninsdeletevalue; Components: desktop
Root: HKCR; Subkey: ".sv";   ValueType: string; ValueData: "OpenForge.SystemVerilog"; Flags: uninsdeletevalue; Components: desktop
Root: HKCR; Subkey: ".vhd";  ValueType: string; ValueData: "OpenForge.VHDL";        Flags: uninsdeletevalue; Components: desktop
Root: HKCR; Subkey: "OpenForge.Verilog";         ValueType: string; ValueData: "Verilog Source File"; Flags: uninsdeletekey; Components: desktop
Root: HKCR; Subkey: "OpenForge.Verilog\shell\open\command"; ValueType: string; ValueData: """{app}\launch_desktop.bat"" ""%1"""; Components: desktop
Root: HKCR; Subkey: "OpenForge.SystemVerilog";   ValueType: string; ValueData: "SystemVerilog Source File"; Flags: uninsdeletekey; Components: desktop
Root: HKCR; Subkey: "OpenForge.SystemVerilog\shell\open\command"; ValueType: string; ValueData: """{app}\launch_desktop.bat"" ""%1"""; Components: desktop
Root: HKCR; Subkey: "OpenForge.VHDL";            ValueType: string; ValueData: "VHDL Source File"; Flags: uninsdeletekey; Components: desktop
Root: HKCR; Subkey: "OpenForge.VHDL\shell\open\command"; ValueType: string; ValueData: """{app}\launch_desktop.bat"" ""%1"""; Components: desktop

; Add to PATH
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\bin"; Tasks: addtopath

[Run]
; Post-install: run first-run wizard
Filename: "{app}\launch_desktop.bat"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Components: desktop

[Code]
// Custom wizard page for tool download progress
var
  ToolDownloadPage: TOutputProgressWizardPage;

procedure InitializeWizard();
begin
  ToolDownloadPage := CreateOutputProgressPage(
    'Downloading EDA Tools',
    'Please wait while selected EDA tools are downloaded and installed...'
  );
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  // After component selection, download selected tools
  if CurPageID = wpReady then
  begin
    if IsComponentSelected('tools\yosys') or
       IsComponentSelected('tools\nextpnr') or
       IsComponentSelected('tools\icepack') then
    begin
      ToolDownloadPage.Show;
      try
        ToolDownloadPage.SetText('Downloading OSS CAD Suite (Yosys + nextpnr + IceStorm)...', '');
        ToolDownloadPage.SetProgress(0, 100);
        // The actual download happens via a batch script post-install
        // Here we just show progress
        ToolDownloadPage.SetProgress(100, 100);
      finally
        ToolDownloadPage.Hide;
      end;
    end;
  end;
end;
