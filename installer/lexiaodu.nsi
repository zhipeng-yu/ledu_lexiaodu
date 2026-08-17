Unicode true
!include "MUI2.nsh"

!ifndef APP_SOURCE
  !error "APP_SOURCE is required"
!endif
!ifndef OUTPUT_DIR
  !error "OUTPUT_DIR is required"
!endif
!ifndef APP_VERSION
  !error "APP_VERSION is required"
!endif
!ifndef APP_FILE_VERSION
  !error "APP_FILE_VERSION is required"
!endif

Name "乐小读"
OutFile "${OUTPUT_DIR}\Lexiaodu-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\Lexiaodu"
InstallDirRegKey HKCU "Software\Lexiaodu" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "${APP_FILE_VERSION}"
VIAddVersionKey "ProductName" "乐小读"
VIAddVersionKey "FileDescription" "乐小读安装程序"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright 2026"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Lexiaodu.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动乐小读"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "乐小读" MainSection
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${APP_SOURCE}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Lexiaodu" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lexiaodu" "DisplayName" "乐小读"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lexiaodu" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lexiaodu" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lexiaodu" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  CreateDirectory "$SMPROGRAMS\乐小读"
  CreateShortcut "$SMPROGRAMS\乐小读\乐小读.lnk" "$INSTDIR\Lexiaodu.exe"
  CreateShortcut "$DESKTOP\乐小读.lnk" "$INSTDIR\Lexiaodu.exe"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\乐小读.lnk"
  Delete "$SMPROGRAMS\乐小读\乐小读.lnk"
  RMDir "$SMPROGRAMS\乐小读"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Lexiaodu"
  DeleteRegKey HKCU "Software\Lexiaodu"
  RMDir /r "$INSTDIR"
SectionEnd
