; NSIS 定制脚本(electron-builder 的 nsis.include 引入)。
;
; 解决的问题:安装/卸载时「文件被占用」。
; Open Studio 的后端是一个独立子进程 open-studio-backend.exe(PyInstaller 打的),由主进程
; spawn。正常退出时 main.cjs 的 before-quit 会 SIGTERM 它;但只要 Electron 是被强杀的
; ——崩溃、任务管理器结束进程、或者安装器自己把主程序关掉——这个后端就变成孤儿进程活下来,
; 并继续占着 resources\backend\ 下的文件。这时候卸载会删不干净:NSIS 报文件被占用,留下
; 一个半残的安装目录,而用户看到的就是「卸载失败 / 卸载不干净」。
;
; electron-builder 自带的进程检查只认主程序 Open Studio.exe,不认这个后端,所以要自己补。
; /T 连带子进程(后端还会再拉起 ffmpeg、声音克隆的 venv python 等)。
; 进程本来就不在时 taskkill 返回非零,直接忽略——这不是错误。

!macro killOpenStudioBackend
  nsExec::Exec 'taskkill /F /T /IM open-studio-backend.exe'
  Pop $0
!macroend

; 装之前杀:覆盖安装(升级)时,旧版本的后端可能还在跑,不杀就写不进新文件。
!macro customInit
  !insertmacro killOpenStudioBackend
!macroend

; 卸载器一启动就杀,早于任何删除动作。
!macro customUnInit
  !insertmacro killOpenStudioBackend
!macroend
