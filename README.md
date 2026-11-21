# LovePetTool

LovePetTool 是 Windows 离线角色包制作工具，与 [LovePet Android](https://github.com/jiangyunxi222/LovePet-Android) 共用 [手机角色包协议 v1](PROTOCOL.md)。按协议整理素材后，选择素材目录和 ZIP、LPK 或 WPK 输出格式，再点「制作或转换」。导入 Android LovePet 后可打开应用内置的角色工作台。

[下载 LovePetTool.exe](https://github.com/jiangyunxi222/LovePetTool/releases/latest)

## 读取、制作与转换

- 「素材文件夹」从约定路径自动识别衣装、动作、表情、字幕和运行库。
- 「角色包」可以读取整理好的素材 ZIP、协议包、旧版 BandoriLove ZIP 和可识别的 ViewerEX LPK、WPK。
- 「制作或转换」在本地生成选定格式。原包缺少运行库时，选择已有兼容运行库所在的目录。

Windows 发布文件为 `LovePetTool.exe`。源码入口使用 Python 3.11 或更新版本，标准库即可运行。

```powershell
python role_builder.py
python role_builder.py pack C:\Roles\Example C:\Exports\Example.wpk --runtime C:\Live2D\runtime
python role_builder.py inspect C:\Exports\Example.wpk
python role_builder.py convert C:\Exports\Example.wpk C:\Exports\Example.lpk
python role_builder.py verify C:\Exports\Example.lpk
```

Windows 下运行 `pwsh -File build-windows.ps1` 可打包 EXE，需要环境中已有 PyInstaller。离线环境可用 `-PyInstallerModules` 指定本地模块目录。协议回归测试运行 `python -m unittest discover -s tests -v`。
