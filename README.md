# BandoriLovePet Windows 角色包制作工具

使用 [手机角色包协议 v1](PROTOCOL.md) 整理文件名、目录和 `role.json`。运行 Windows 制作工具，选择素材目录，选择输出 ZIP、LPK 或 WPK，再点「制作或转换」。导入更新后的 Android LovePet，即可打开内置角色工作台。

## 读取、制作与转换

- 「素材文件夹」从约定路径自动识别衣装、动作、表情、字幕和运行库。
- 「角色包」可以读取整理好的素材 ZIP、协议包、旧版 BandoriLove ZIP 和可识别的 ViewerEX LPK、WPK。
- 「制作或转换」在本地生成选定格式。原包缺少运行库时，选择已有兼容运行库所在的目录。

Windows 分发文件为 `dist/BandoriLovePetRoleBuilder.exe`。源码入口使用 Python 3.11 或更新版本，标准库即可运行。

```powershell
python role_builder.py
python role_builder.py pack C:\Roles\Example C:\Exports\Example.wpk --runtime C:\Live2D\runtime
python role_builder.py inspect C:\Exports\Example.wpk
python role_builder.py convert C:\Exports\Example.wpk C:\Exports\Example.lpk
python role_builder.py verify C:\Exports\Example.lpk
```

`migrate_libraries.py` 用于在原有 BandoriLove 工作区中重建 Garupa 和 OurNotes 手机库。它读取原库发布目录中的索引、素材和来源记录。

Windows 下运行 `pwsh -File build-windows.ps1` 可打包 EXE，需要环境中已有 PyInstaller。离线环境可用 `-PyInstallerModules` 指定本地模块目录。协议回归测试运行 `python -m unittest discover -s tests -v`。
