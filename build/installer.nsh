; NSIS 定制脚本(electron-builder 的 nsis.include 引入)。
;
; 解决的问题:安装/卸载时「文件被占用」。
; Mosael 的后端是一个独立子进程 mosael-backend.exe(PyInstaller 打的),由主进程
; spawn。正常退出时 main.cjs 的 before-quit 会 SIGTERM 它;但只要 Electron 是被强杀的
; ——崩溃、任务管理器结束进程、或者安装器自己把主程序关掉——这个后端就变成孤儿进程活下来,
; 并继续占着 resources\backend\ 下的文件。这时候卸载会删不干净:NSIS 报文件被占用,留下
; 一个半残的安装目录,而用户看到的就是「卸载失败 / 卸载不干净」。
;
; electron-builder 自带的进程检查只认主程序 Mosael.exe,不认这个后端,所以要自己补。
; /T 连带子进程(后端还会再拉起 ffmpeg、声音克隆的 venv python 等)。
; 进程本来就不在时 taskkill 返回非零,直接忽略——这不是错误。

!macro killMosaelBackend
  nsExec::Exec 'taskkill /F /T /IM mosael-backend.exe'
  Pop $0
!macroend

; 装之前杀:覆盖安装(升级)时,旧版本的后端可能还在跑,不杀就写不进新文件。
!macro customInit
  !insertmacro killMosaelBackend
!macroend

; 卸载器一启动就杀,早于任何删除动作。
!macro customUnInit
  !insertmacro killMosaelBackend
!macroend

; ── 文件关联:只进「打开方式」和「默认应用」的候选,不抢默认程序 ─────────────────────────
;
; 此前用的是 electron-builder 的 fileAssociations:它的 APP_ASSOCIATE 第一行就把
; Software\Classes\.mp4 的默认值写成自己的类 —— 装完 Mosael,电脑上所有视频、音频的默认程序和图标
; 都变成了 Mosael(用户:「理论上应该是设置默认打开方式后才替换才对吧」)。所以 Windows 这边不再交给它
; (package.json 里 fileAssociations 只留在 mac 下),在这里自己登记:
;   · 两个 ProgID(Mosael.Video / Mosael.Audio):用它打开时怎么启动、什么图标;
;   · 每种扩展名的 OpenWithProgids 里挂上 —— 右键「打开方式」里有 Mosael;
;   · Capabilities + RegisteredApplications —— 「设置 → 默认应用」里能选 Mosael。
; **扩展名的默认值一个都不写**:默认程序归用户自己定。扩展名清单和 package.json 的 mac.fileAssociations 是同一份
; (backend/tests/test_windows_file_associations.py 钉着)。
;
; 升级时顺带把旧版本抢走的还回去:扩展名的默认值还指着旧的类(「视频」「音频」)就删掉这个默认值 ——
; 用户自己在「打开方式 → 始终使用」里选过的记在 Explorer 的 UserChoice 里,不在这儿,不受影响。

!include "LogicLib.nsh"

!define MOSAEL_CAPABILITIES "Software\Mosael\Capabilities"

!macro mosaelProgId PROGID DESCRIPTION
  WriteRegStr SHCTX "Software\Classes\${PROGID}" "" "${DESCRIPTION}"
  WriteRegStr SHCTX "Software\Classes\${PROGID}\DefaultIcon" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME},0"
  WriteRegStr SHCTX "Software\Classes\${PROGID}\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
!macroend

; 一种扩展名:进「打开方式」和默认应用的候选;旧版本抢走的默认值还回去。
!macro mosaelAssociate EXT PROGID OLDCLASS
  WriteRegStr SHCTX "Software\Classes\.${EXT}\OpenWithProgids" "${PROGID}" ""
  WriteRegStr SHCTX "${MOSAEL_CAPABILITIES}\FileAssociations" ".${EXT}" "${PROGID}"
  DeleteRegValue SHCTX "Software\Classes\.${EXT}\OpenWithProgids" "${OLDCLASS}"
  ReadRegStr $0 SHCTX "Software\Classes\.${EXT}" ""
  ${If} $0 == "${OLDCLASS}"
    DeleteRegValue SHCTX "Software\Classes\.${EXT}" ""
  ${EndIf}
!macroend

!macro mosaelUnassociate EXT PROGID
  DeleteRegValue SHCTX "Software\Classes\.${EXT}\OpenWithProgids" "${PROGID}"
!macroend

; 旧版本留下的类:只在它确实是 Mosael 写的(打开命令就是旧版的那一句)时才删。
!macro mosaelDropOldClass OLDCLASS
  ReadRegStr $0 SHCTX "Software\Classes\${OLDCLASS}\shell\open\command" ""
  ${If} $0 == '$INSTDIR\${APP_EXECUTABLE_FILENAME} "%1"'
    DeleteRegKey SHCTX "Software\Classes\${OLDCLASS}"
  ${EndIf}
!macroend

!macro mosaelFileTypes ACTION
  ; MOSAEL-VIDEO-EXTS: mp4 mov m4v mkv webm
  !insertmacro ${ACTION} "mp4" "Mosael.Video" "视频"
  !insertmacro ${ACTION} "mov" "Mosael.Video" "视频"
  !insertmacro ${ACTION} "m4v" "Mosael.Video" "视频"
  !insertmacro ${ACTION} "mkv" "Mosael.Video" "视频"
  !insertmacro ${ACTION} "webm" "Mosael.Video" "视频"
  ; MOSAEL-AUDIO-EXTS: mp3 wav m4a aac flac
  !insertmacro ${ACTION} "mp3" "Mosael.Audio" "音频"
  !insertmacro ${ACTION} "wav" "Mosael.Audio" "音频"
  !insertmacro ${ACTION} "m4a" "Mosael.Audio" "音频"
  !insertmacro ${ACTION} "aac" "Mosael.Audio" "音频"
  !insertmacro ${ACTION} "flac" "Mosael.Audio" "音频"
!macroend

; 卸载时的那一版只要两个参数:第三个(旧类)吞掉。
!macro mosaelUnassociate3 EXT PROGID OLDCLASS
  !insertmacro mosaelUnassociate "${EXT}" "${PROGID}"
!macroend

!macro customInstall
  !insertmacro mosaelProgId "Mosael.Video" "Mosael 视频"
  !insertmacro mosaelProgId "Mosael.Audio" "Mosael 音频"
  WriteRegStr SHCTX "${MOSAEL_CAPABILITIES}" "ApplicationName" "Mosael"
  WriteRegStr SHCTX "${MOSAEL_CAPABILITIES}" "ApplicationDescription" "Mosael 视频创作工作台"
  !insertmacro mosaelFileTypes mosaelAssociate
  WriteRegStr SHCTX "Software\RegisteredApplications" "Mosael" "${MOSAEL_CAPABILITIES}"
  !insertmacro mosaelDropOldClass "视频"
  !insertmacro mosaelDropOldClass "音频"
  ; 告诉资源管理器关联变了:图标当场刷新,不用等重启。
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend

!macro customUnInstall
  !insertmacro mosaelFileTypes mosaelUnassociate3
  DeleteRegValue SHCTX "Software\RegisteredApplications" "Mosael"
  DeleteRegKey SHCTX "${MOSAEL_CAPABILITIES}"
  DeleteRegKey /ifempty SHCTX "Software\Mosael"
  DeleteRegKey SHCTX "Software\Classes\Mosael.Video"
  DeleteRegKey SHCTX "Software\Classes\Mosael.Audio"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend
